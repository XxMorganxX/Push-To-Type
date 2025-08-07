#!/usr/bin/env python3
"""
Push-to-Talk WebSocket Transcription with Keyboard Injection
Fixed version using AssemblyAI's official sample code approach
"""

import json
import pyaudio
import threading
import sys
import os
import time
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict, Set, Tuple
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv
from urllib.parse import urlencode
import websocket

from core.ptt_keybind_manager import PTTKeybind
from core.unicode_injector import UnicodeInjector
from pynput import keyboard

load_dotenv()


def clean_transcript(text: str) -> str:
    """Deprecated: string-based cleaning retained for logging only."""
    no_punct_chars = [ch for ch in text if not unicodedata.category(ch).startswith('P')]
    cleaned = ''.join(no_punct_chars).lower()
    return " ".join(cleaned.split())


class TranscriptionState(Enum):
    """States for transcription session."""
    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


@dataclass
class AssemblyAIConfig:
    """Configuration for AssemblyAI WebSocket connection."""
    api_key: str
    sample_rate: int = 16000
    
    @property
    def ws_url(self) -> str:
        """Get the WebSocket URL with parameters."""
        connection_params = {
            "sample_rate": self.sample_rate,
            "format_turns": True,  # Request formatted final transcripts
        }
        api_endpoint_base = "wss://streaming.assemblyai.com/v3/ws"
        return f"{api_endpoint_base}?{urlencode(connection_params)}"


class PTTTranscriber:
    """
    WebSocket transcriber with keyboard injection output.
    """
    
    def __init__(self, config: AssemblyAIConfig, word_replacements: Optional[Dict[str, str]] = None, joiner_values: Optional[List[str]] = None, phrase_replacements: Optional[Dict[str, str]] = None):
        """Initialize the transcriber."""
        self.config = config
        self.state = TranscriptionState.IDLE
        
        # Audio configuration
        self.chunk_duration_ms = 20  # 20 ms chunks for snappier streaming
        self.chunk_size = int(self.config.sample_rate * self.chunk_duration_ms / 1000)
        self.min_send_duration_ms = 50  # API requires 50–1000 ms per message
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        
        # Components  
        self.injector = UnicodeInjector(typing_delay=0.015)  # Slower typing to prevent interference
        # Word replacement mapping (token -> replacement string)
        self.word_replacements: Dict[str, str] = {}
        if word_replacements:
            # Normalize keys to lowercase to match cleaned tokens
            self.word_replacements = {str(k).lower(): str(v) for k, v in word_replacements.items()}
        # Tokens whose replacements should not have spaces around them (e.g., "/", "-", ":")
        self.joiner_values: Set[str] = set(joiner_values or [])
        # Phrase replacements (e.g., "forward slash" -> "/")
        self.phrase_replacements: Dict[Tuple[str, ...], str] = {}
        if phrase_replacements:
            for k, v in phrase_replacements.items():
                key_tuple = tuple(str(k).lower().split())
                if key_tuple:
                    self.phrase_replacements[key_tuple] = str(v)
        
        # WebSocket and audio
        self.ws_app: Optional[websocket.WebSocketApp] = None
        self.audio_stream: Optional[pyaudio.Stream] = None
        self.pyaudio_instance = pyaudio.PyAudio()
        
        # Threading
        self.audio_thread: Optional[threading.Thread] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.session_id: Optional[str] = None
        self.ws_ready = threading.Event()  # Track when WebSocket is ready
        
        # Track transcribed text
        self.total_characters_typed = 0  # Session stats
        self.turn_count = 0  # Track number of turns
        self.session_text = ""  # Accumulate all text across turns
        self.typing_lock = threading.Lock()  # Prevent simultaneous typing
        
        # Word-based streaming state
        self.committed_word_count = 0  # Count of finalized words emitted in current turn
        self.current_turn_order: Optional[int] = None
        self.last_output_chunk: str = ""
        
    def _on_ws_open(self, ws):
        """Called when WebSocket connection is established."""
        print("✅ WebSocket connection opened")
        self.state = TranscriptionState.LISTENING
        self.ws_ready.set()  # Signal that WebSocket is ready
        self._start_audio_streaming()

    def _dedupe_adjacent_words(self, words: List[str]) -> List[str]:
        """Collapse adjacent duplicate words in a list while preserving order.

        Example: ["a", "a", "b", "b", "b", "c"] -> ["a", "b", "c"]
        """
        if not words:
            return words
        deduped: List[str] = [words[0]]
        for w in words[1:]:
            if w != deduped[-1]:
                deduped.append(w)
        return deduped
    
    def _clean_word_token(self, token: str) -> str:
        """Lowercase and strip punctuation except for tokens we map directly."""
        if not token:
            return ""
        # If token matches a direct word replacement key, keep as-is lowercased
        t = token.strip().lower()
        if t in self.word_replacements:
            return t
        # Else strip punctuation
        filtered = ''.join(ch for ch in token if not unicodedata.category(ch).startswith('P'))
        return filtered.strip().lower()

    def _apply_phrase_replacements(self, tokens: List[str]) -> List[str]:
        if not self.phrase_replacements:
            return tokens
        # Sort patterns by descending length for greedy longest-match
        patterns = sorted(self.phrase_replacements.keys(), key=lambda t: -len(t))
        out: List[str] = []
        i = 0
        while i < len(tokens):
            matched = False
            for pat in patterns:
                n = len(pat)
                if n == 0 or i + n > len(tokens):
                    continue
                window = tuple(tokens[i:i+n])
                if window == pat:
                    out.append(self.phrase_replacements[pat])
                    i += n
                    matched = True
                    break
            if not matched:
                out.append(tokens[i])
                i += 1
        return out

    def _on_ws_message(self, ws, message):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            # Debug: Show ALL received messages
            #print(f"\n📨 RECEIVED MESSAGE: {data}")
            if msg_type == "Begin":
                self.session_id = data.get('id')
                print(f"🎉 Session began: ID={self.session_id}")
                self.state = TranscriptionState.TRANSCRIBING
            elif msg_type == "Turn":
                is_final = data.get('end_of_turn', False)
                is_formatted = data.get('turn_is_formatted', False)
                turn_order = data.get('turn_order', None)
                if turn_order is not None and turn_order != self.current_turn_order:
                    self.current_turn_order = turn_order
                    self.committed_word_count = 0
                # Process only unformatted words to avoid duplicate final outputs
                words = data.get('words') or []
                if words and not is_formatted:
                    with self.typing_lock:
                        new_tokens: List[str] = []
                        max_final_index = self.committed_word_count
                        for idx in range(self.committed_word_count, len(words)):
                            w = words[idx]
                            if not w.get('word_is_final', False):
                                break
                            raw = (w.get('text', '') or '').strip()
                            cleaned = self._clean_word_token(raw)
                            if cleaned:
                                token = self.word_replacements.get(cleaned, cleaned)
                                if token:
                                    new_tokens.append(token)
                            else:
                                # If token is punctuation (e.g., '/') allow it through if configured as a joiner
                                if raw and raw in self.joiner_values:
                                    new_tokens.append(raw)
                            max_final_index = idx + 1
                        if max_final_index > self.committed_word_count:
                            self.committed_word_count = max_final_index
                            if new_tokens:
                                # Apply phrase-level replacements (e.g., "forward slash" -> "/")
                                new_tokens = self._apply_phrase_replacements(new_tokens)
                                # Build string honoring joiners (no spaces around joiner tokens)
                                parts: List[str] = []
                                for i, tok in enumerate(new_tokens):
                                    is_joiner = tok in self.joiner_values
                                    if i == 0:
                                        # Only add leading space if needed and first token is not a joiner
                                        if (not is_joiner) and self.session_text and not self.session_text.endswith(" ") and not self.session_text.endswith(tuple(self.joiner_values)):
                                            parts.append(" ")
                                    else:
                                        prev_tok = new_tokens[i-1]
                                        prev_is_joiner = prev_tok in self.joiner_values
                                        if not prev_is_joiner and not is_joiner:
                                            parts.append(" ")
                                    parts.append(tok)
                                to_type = "".join(parts)
                                if to_type == self.last_output_chunk or (to_type and self.session_text.endswith(to_type)):
                                    print("\n⏭️  Skipping duplicate chunk")
                                else:
                                    print("\n⌨️  WORDS: '%s'" % to_type)
                                    self.injector.inject_text(to_type)
                                    self.session_text += to_type
                                    self.total_characters_typed += len(to_type)
                                    self.last_output_chunk = to_type
                # Only close out the turn for unformatted final message
                if is_final and not is_formatted:
                    if self.session_text and not self.session_text.endswith(' '):
                        self.injector.inject_text(' ')
                        self.session_text += ' '
                        self.total_characters_typed += 1
                    self.committed_word_count = 0
                    self.current_turn_order = None
                    self.turn_count += 1
                    print(f"✅ FINAL TURN #{self.turn_count}")
                    # Reset last chunk for next turn to avoid suppressing legitimate text
                    self.last_output_chunk = ""
            elif msg_type == "Termination":
                audio_duration = data.get('audio_duration_seconds', 0)
                session_duration = data.get('session_duration_seconds', 0)
                print(f"\n⚠️ Session Terminated: Audio={audio_duration}s, Session={session_duration}s")
        except json.JSONDecodeError as e:
            print(f"❌ Error decoding message: {e}")
        except Exception as e:
            print(f"❌ Error handling message: {e}")
    
    def _on_ws_error(self, ws, error):
        """Called when a WebSocket error occurs."""
        print(f"❌ WebSocket Error: {error}")
        # Don't immediately set error state - might be recoverable
        if "Connection is already closed" not in str(error):
            print("⚠️ WebSocket error occurred, but continuing...")
        self.state = TranscriptionState.ERROR
        self.stop_event.set()
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection is closed."""
        if close_status_code == 1000:
            print(f"🔌 WebSocket closed normally: {close_msg}")
        else:
            print(f"🔌 WebSocket Disconnected: Status={close_status_code}, Msg={close_msg}")
            if close_status_code != 1000:
                print("⚠️ Connection closed unexpectedly - this is normal after PTT release")
        
        self.state = TranscriptionState.IDLE
        self.stop_event.set()
        self.ws_ready.clear()  # WebSocket no longer ready
        self._cleanup_audio()
        # Pause monitor not used in word-based streaming
    
    def _start_audio_streaming(self):
        """Start audio streaming in a separate thread."""
        def stream_audio():
            print("🎙️ Starting audio streaming...")
            send_buffer = bytearray()
            bytes_per_sample = self.pyaudio_instance.get_sample_size(self.audio_format)
            bytes_per_frame = bytes_per_sample * self.channels
            min_send_frames = int(self.config.sample_rate * self.min_send_duration_ms / 1000)
            min_send_bytes = min_send_frames * bytes_per_frame
            send_count = 0

            while not self.stop_event.is_set():
                try:
                    if (self.audio_stream and 
                        self.ws_app and 
                        hasattr(self.ws_app, 'sock') and 
                        self.ws_app.sock and 
                        self.ws_ready.is_set()):
                        
                        audio_data = self.audio_stream.read(
                            self.chunk_size, 
                            exception_on_overflow=False
                        )
                        send_buffer.extend(audio_data)

                        # Send in >= 50 ms chunks to satisfy API requirement
                        while len(send_buffer) >= min_send_bytes:
                            to_send = bytes(send_buffer[:min_send_bytes])
                            del send_buffer[:min_send_bytes]
                            self.ws_app.send(to_send, websocket.ABNF.OPCODE_BINARY)
                            send_count += 1

                            # Print a status dot roughly every 500 ms of audio sent
                            dots_every = max(1, int(500 / self.min_send_duration_ms))
                            if send_count % dots_every == 0:
                                print(".", end="", flush=True)
                        
                except Exception as e:
                    if not self.stop_event.is_set():
                        print(f"\n❌ Error streaming audio: {e}")
                    break

            # Flush any remaining audio, padding to minimum duration if needed
            try:
                if (send_buffer and self.ws_app and hasattr(self.ws_app, 'sock') and 
                    self.ws_app.sock and self.ws_ready.is_set()):
                    if len(send_buffer) < min_send_bytes:
                        padding = bytes(min_send_bytes - len(send_buffer))
                        send_buffer.extend(padding)
                    self.ws_app.send(bytes(send_buffer), websocket.ABNF.OPCODE_BINARY)
            except Exception as _:
                pass

            print("\n🎙️ Audio streaming stopped")
        
        self.audio_thread = threading.Thread(target=stream_audio)
        self.audio_thread.daemon = True
        self.audio_thread.start()

    # Pause monitor removed for word-based streaming
    
    def start_transcription(self):
        """Start the transcription session."""
        try:
            self.state = TranscriptionState.CONNECTING
            print("🔄 Starting transcription session...")
            
            # Open microphone stream
            print("🎙️ Opening microphone...")
            self.audio_stream = self.pyaudio_instance.open(
                input=True,
                frames_per_buffer=self.chunk_size,
                channels=self.channels,
                format=self.audio_format,
                rate=self.config.sample_rate,
            )
            print("✅ Microphone opened successfully")
            
            # Create WebSocketApp
            self.ws_app = websocket.WebSocketApp(
                self.config.ws_url,
                header={"Authorization": self.config.api_key},
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            
            # Run WebSocketApp in a separate thread
            self.ws_thread = threading.Thread(target=self.ws_app.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
            print("🔄 WebSocket connection starting...")
            
        except Exception as e:
            print(f"❌ Failed to start transcription: {e}")
            self.state = TranscriptionState.ERROR
    
    def stop_transcription(self):
        """Stop the transcription session."""
        print("\n🛑 Stopping audio streaming...")
        
        # Signal stop audio streaming but keep WebSocket open momentarily
        self.stop_event.set()
        
        # Wait for audio streaming to stop
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        
        # Cleanup audio first
        self._cleanup_audio()
        
        # Wait a moment for any final transcription messages
        print("⏱️  Waiting for final transcription...")
        time.sleep(1.0)
        
        # Now send termination and close WebSocket
        if (self.ws_app and 
            hasattr(self.ws_app, 'sock') and 
            self.ws_app.sock):
            try:
                terminate_message = {"type": "Terminate"}
                print(f"📤 Sending termination message: {json.dumps(terminate_message)}")
                self.ws_app.send(json.dumps(terminate_message))
                time.sleep(0.3)  # Give time for final messages
            except Exception as e:
                print(f"❌ Error sending termination message: {e}")
        
        # Close WebSocket
        self.ws_ready.clear()
        if self.ws_app:
            try:
                self.ws_app.close()
            except Exception as _:
                pass
        
        # Wait for WebSocket thread to finish
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=1.0)
        
        # Stop typing
        self.injector.stop()
        
        # Show session summary
        if hasattr(self, 'total_characters_typed') and self.total_characters_typed > 0:
            print(f"📊 Session summary: {self.total_characters_typed} characters typed total")
            print(f"📝 Full session text: '{getattr(self, 'session_text', '')}'")
        
        # Reset tracking for next session
        self.total_characters_typed = 0
        self.turn_count = 0
        self.session_text = ""
        self.stop_event.clear()  # Reset for next session
        
        self.state = TranscriptionState.IDLE
        print("✅ Transcription stopped")
    
    def _cleanup_audio(self):
        """Clean up audio resources."""
        if self.audio_stream:
            if self.audio_stream.is_active():
                self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
    
    def cleanup(self):
        """Clean up all resources."""
        self.injector.stop()
        self._cleanup_audio()
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()


class PushToTalkApp:
    """
    Push-to-Talk application with keyboard injection.
    """
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize the PTT application."""
        self.config = self._load_config(config_path)
        self.transcriber: Optional[PTTTranscriber] = None
        self.is_transcribing = False
        
        # Direct keyboard handling like debug script
        self.pressed_keys = set()
        self.keyboard_listener: Optional[keyboard.Listener] = None
        self.ptt_keybind = PTTKeybind(
            modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
        )
        self.ptt_active = False
        print(f"Debug: Created keybind with modifiers: {self.ptt_keybind.modifiers}")
        
    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"❌ Config file not found: {config_path}")
            print("Please create a config.json file with your AssemblyAI API key")
            sys.exit(1)
            
        with open(config_file, 'r') as f:
            return json.load(f)
    
    def _setup_ptt(self):
        """Configure push-to-talk keybind using direct keyboard listener."""
        print("📍 Push-to-Talk configured: Both Shift Keys (left + right)")
        print(f"   Keybind modifiers: {self.ptt_keybind.modifiers}")
        
        # Start direct keyboard listener
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self.keyboard_listener.start()
    
    def _on_key_press(self, key):
        """Handle key press events directly."""
        self.pressed_keys.add(key)
        
        # Use the exact same matching logic as debug script
        matches = self.ptt_keybind.matches(self.pressed_keys, key)
        
        if matches and not self.ptt_active:
            self.ptt_active = True
            self._on_ptt_press()
    
    def _on_key_release(self, key):
        """Handle key release events directly."""
        self.pressed_keys.discard(key)
        
        # Check if keybind is no longer held
        if self.ptt_active:
            still_held = self.ptt_keybind.is_still_held(self.pressed_keys)
            if not still_held:
                self.ptt_active = False
                self._on_ptt_release()
    
    def _on_ptt_press(self):
        """Handle PTT key press (start transcription)."""
        print("\n" + "="*60)
        print(f"🎤 PTT PRESSED at {time.time():.3f} - Recording...")
        print("💡 Text will appear at your cursor position!")
        print("="*60)
        
        if not self.is_transcribing:
            self._start_transcription()
            # Indicator removed
    
    def _on_ptt_release(self):
        """Handle PTT key release (stop transcription)."""
        print("\n" + "="*60)
        print("🔴 PTT RELEASED - Stopping...")
        print("="*60)
        
        if self.is_transcribing:
            self._stop_transcription()
            # Indicator removed
    
    def _start_transcription(self):
        """Start the transcription session."""
        if self.is_transcribing:
            return
            
        self.is_transcribing = True
        
        try:
            # Get API key
            api_key = os.getenv("ASSEMBLYAI_API_KEY")
            if not api_key:
                api_key = self.config["assemblyai"].get("api_key")
                if api_key == "in_env" or not api_key:
                    print("❌ No AssemblyAI API key found!")
                    print("Set ASSEMBLYAI_API_KEY environment variable or update config.json")
                    self.is_transcribing = False
                    return
            
            # Create AssemblyAI config
            ai_config = AssemblyAIConfig(
                api_key=api_key,
                sample_rate=self.config["assemblyai"]["sample_rate"]
            )
            
            # Create transcriber with word replacements from config (optional)
            cfg = self.config if isinstance(self.config, dict) else {}
            # Default mappings to ensure common spoken punctuations work out of the box
            default_word_replacements = {
                "slash": "/",
                "backslash": "\\",
                "underscore": "_",
                "dash": "-",
                "hyphen": "-",
                "colon": ":",
                "semicolon": ";",
                "dot": ".",
                "period": ".",
                "comma": ","
            }
            user_word_replacements = cfg.get("word_replacements", {})
            word_replacements = {**default_word_replacements, **user_word_replacements}
            # Joiner values: replacements that should glue to adjacent tokens without spaces
            joiner_values = cfg.get("word_joiners", ["/", "-", ":", "@", "#"]) 
            # Phrase replacements support: spellings of punctuation
            phrase_replacements = cfg.get("phrase_replacements", {
                "forward slash": "/",
                "back slash": "\\",
                "backslash": "\\",
                "colon": ":",
                "dot": ".",
                "period": ".",
                "comma": ",",
                "dash": "-",
                "hyphen": "-"
            })
            self.transcriber = PTTTranscriber(
                ai_config,
                word_replacements=word_replacements,
                joiner_values=joiner_values,
                phrase_replacements=phrase_replacements,
            )
            
            # Adjust typing delay if configured
            if "typing" in self.config:
                self.transcriber.injector.typing_delay = self.config["typing"].get(
                    "delay_ms", 5
                ) / 1000
            
            # Start transcription
            self.transcriber.start_transcription()
            
        except Exception as e:
            print(f"❌ Failed to start transcription: {e}")
            import traceback
            traceback.print_exc()
            self.is_transcribing = False
    
    def _stop_transcription(self):
        """Stop the transcription session."""
        if not self.is_transcribing or not self.transcriber:
            return
        
        # Stop the transcriber
        if self.transcriber:
            self.transcriber.stop_transcription()
        
        # Clean up
        self.transcriber = None
        self.is_transcribing = False
        
        print("✅ Ready for next PTT press")
    
    def cleanup(self):
        """Cleanup all resources."""
        print("\n🔄 Cleaning up...")
        
        # Stop transcription if active
        if self.is_transcribing:
            self._stop_transcription()
        
        # Stop keyboard listener
        if self.keyboard_listener:
            print("⌨️  Stopping keyboard listener...")
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        
        # Cleanup transcriber
        if self.transcriber:
            self.transcriber.cleanup()
        # Indicator removed
        
        print("✅ Cleanup complete")
    
    def run(self):
        """Run the main application loop."""
        print("\n" + "="*60)
        print(" 🎙️  PUSH-TO-TALK TRANSCRIPTION WITH KEYBOARD INJECTION")
        print("="*60)
        
        # Check for API key
        api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if not api_key:
            api_key = self.config["assemblyai"].get("api_key")
            if api_key == "in_env" or not api_key:
                print("\n⚠️  WARNING: No API key configured!")
                print("Set ASSEMBLYAI_API_KEY environment variable")
                print("Or update 'api_key' in config.json")
                print()
        
        ptt_key = self.config["keybinds"].get("ptt", "leftshift+rightshift")
        typing_delay = self.config.get("typing", {}).get("delay_ms", 5)
        
        if ptt_key == "leftshift+rightshift":
            print("\n🎯 HOLD [Left Shift + Right Shift] simultaneously to record")
            print("   Both shift keys must be pressed together")
            print("   RELEASE either shift to stop")
        else:
            print("\n🎯 HOLD [%s] to start recording" % ptt_key)
            print("   RELEASE to stop")
        print("\n⌨️  Text streams as you speak!")
        print("   Typing delay: %dms per character" % typing_delay)
        print("   Words appear in real-time while talking")
        print("\n⚠️  Press Ctrl+C to exit")
        print("="*60 + "\n")
        
        # Setup PTT
        self._setup_ptt()
        
        # Keep running until interrupted
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\n⚠️ Interrupt received...")
        finally:
            self.cleanup()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Push-to-Talk Transcription with Keyboard Injection"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    
    args = parser.parse_args()
    
    # Create application
    app = PushToTalkApp(config_path=args.config)
    
    # Run application
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n⚠️ Exiting...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("👋 Goodbye!")


if __name__ == "__main__":
    main()