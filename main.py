#!/usr/bin/env python3
"""
Push-to-Talk WebSocket Transcription with Keyboard Injection
Fixed version using AssemblyAI's official sample code approach
"""

import json
import signal
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

from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from core.event_tap_listener import EventTapPTTListener
# Note: previously imported CGEventSourceKeyState and kCGEventSourceStateCombinedSessionState are unused; removed
from core.unicode_injector import UnicodeInjector
from core.ptt_indicator import PTTIndicator, create_indicator
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
    
    def __init__(
        self,
        config: AssemblyAIConfig,
        word_replacements: Optional[Dict[str, str]] = None,
        joiner_values: Optional[List[str]] = None,
        phrase_replacements: Optional[Dict[str, str]] = None,
        audio_chunk_duration_ms: Optional[int] = None,
        min_send_ms: Optional[int] = None,
        prebuffer_ms: Optional[int] = None,
        typing_mode: Optional[str] = None,
        preserve_clipboard: Optional[bool] = None,
    ):
        """Initialize the transcriber."""
        self.config = config
        self.state = TranscriptionState.IDLE
        
        # Audio configuration (configurable)
        # Clamp chunk duration to sensible real-time ranges (5–50ms)
        if audio_chunk_duration_ms is None:
            self.chunk_duration_ms = 20
        else:
            try:
                self.chunk_duration_ms = max(5, min(50, int(audio_chunk_duration_ms)))
            except Exception:
                self.chunk_duration_ms = 20
        self.chunk_size = int(self.config.sample_rate * self.chunk_duration_ms / 1000)
        # API requires 50–1000 ms per message; clamp accordingly
        if min_send_ms is None:
            self.min_send_duration_ms = 50
        else:
            try:
                self.min_send_duration_ms = max(50, min(1000, int(min_send_ms)))
            except Exception:
                self.min_send_duration_ms = 50
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        # Prebuffer for initial audio while WS connects
        try:
            self.prebuffer_ms = 250 if prebuffer_ms is None else max(0, min(1000, int(prebuffer_ms)))
        except Exception:
            self.prebuffer_ms = 250
        self.prebuffer = bytearray()
        self._prebuffer_lock = threading.Lock()
        
        # Components
        # Default to paste mode to avoid long queues of per-character HID events (which can flush on Ctrl+C)
        mode = (typing_mode or "paste").strip().lower()
        if mode not in ("keystroke", "paste"):
            mode = "paste"
        self.injector = UnicodeInjector(
            typing_delay=0.015,
            mode=mode,  # type: ignore[arg-type]
            preserve_clipboard=True if preserve_clipboard is None else bool(preserve_clipboard),
        )
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
        
        # Thread-safe audio cleanup
        self._audio_cleanup_lock = threading.Lock()
        self._audio_cleaned_up = False
        
        # Track transcribed text
        self.total_characters_typed = 0  # Session stats
        self.turn_count = 0  # Track number of turns
        self.session_text = ""  # Accumulate all text across turns
        self.typing_lock = threading.Lock()  # Prevent simultaneous typing
        
        # Word-based streaming state
        self.committed_word_count = 0  # Count of finalized words emitted in current turn
        self.current_turn_order: Optional[int] = None
        self.last_output_chunk: str = ""
        # Suppress output flag to prevent injection during shutdown/stop
        self._suppress_output = False
        # Track last WebSocket message timestamp for quiet-period waits
        self._last_ws_msg_time = time.time()
        
    def _on_ws_open(self, ws):
        """Called when WebSocket connection is established."""
        print("✅ WebSocket connection opened")
        self.state = TranscriptionState.LISTENING
        self.ws_ready.set()  # Signal that WebSocket is ready
        # Ensure audio thread is running
        if (not self.audio_thread) or (not self.audio_thread.is_alive()):
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
            self._last_ws_msg_time = time.time()
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
                if words and not is_formatted and not self._suppress_output:
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
                                    #print("\n⌨️  WORDS: '%s'" % to_type)
                                    self.injector.inject_text(to_type)
                                    self.session_text += to_type
                                    self.total_characters_typed += len(to_type)
                                    self.last_output_chunk = to_type
                # Only close out the turn for unformatted final message
                if is_final and not is_formatted and not self._suppress_output:
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
        # Don't cleanup audio here - let stop_transcription handle it
        # This prevents double-free errors
    
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
            # Prebuffer capacity in bytes
            prebuffer_max_bytes = 0
            try:
                if getattr(self, 'prebuffer_ms', 0) > 0:
                    prebuffer_frames = int(self.config.sample_rate * self.prebuffer_ms / 1000)
                    prebuffer_max_bytes = max(0, prebuffer_frames * bytes_per_frame)
            except Exception:
                prebuffer_max_bytes = 0

            while not self.stop_event.is_set():
                try:
                    # Check if audio stream is valid and not cleaned up
                    with self._audio_cleanup_lock:
                        stream_valid = (self.audio_stream and not self._audio_cleaned_up)

                    if not stream_valid:
                        if not self.stop_event.is_set():
                            time.sleep(0.01)
                        continue

                    # Always read audio to avoid losing initial speech
                    try:
                        audio_data = self.audio_stream.read(
                            self.chunk_size,
                            exception_on_overflow=False
                        )
                    except Exception as stream_e:
                        if not self.stop_event.is_set():
                            print(f"\n❌ Audio stream error: {stream_e}")
                        break

                    # If WS not ready, accumulate prebuffer and continue
                    if not (self.ws_app and hasattr(self.ws_app, 'sock') and self.ws_app.sock and self.ws_ready.is_set()):
                        if prebuffer_max_bytes > 0:
                            with self._prebuffer_lock:
                                self.prebuffer.extend(audio_data)
                                if len(self.prebuffer) > prebuffer_max_bytes:
                                    self.prebuffer = self.prebuffer[-prebuffer_max_bytes:]
                        continue

                    # Drain prebuffer first
                    if self.prebuffer:
                        with self._prebuffer_lock:
                            if self.prebuffer:
                                send_buffer.extend(self.prebuffer)
                                self.prebuffer = bytearray()

                    # Append latest audio
                    send_buffer.extend(audio_data)

                    # Send in >= min_send_bytes chunks
                    while len(send_buffer) >= min_send_bytes:
                        to_send = bytes(send_buffer[:min_send_bytes])
                        del send_buffer[:min_send_bytes]
                        if (self.ws_app and hasattr(self.ws_app, 'sock') and self.ws_app.sock):
                            self.ws_app.send(to_send, websocket.ABNF.OPCODE_BINARY)
                            send_count += 1
                            dots_every = max(1, int(500 / self.min_send_duration_ms))
                            if send_count % dots_every == 0:
                                print(".", end="", flush=True)
                        else:
                            break
                except Exception as e:
                    if not self.stop_event.is_set():
                        print(f"\n❌ Error in audio streaming loop: {e}")
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
            # Allow output again for new session and reset quiet timer
            self._suppress_output = False
            self._last_ws_msg_time = time.time()
            # Ensure injector is enabled for new session
            try:
                if hasattr(self.injector, "enable"):
                    self.injector.enable()
            except Exception:
                pass
            
            # Reset audio cleanup flag for new session
            with self._audio_cleanup_lock:
                self._audio_cleaned_up = False
            
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
            # Start audio capture immediately (fills prebuffer while WS connects)
            if (not self.audio_thread) or (not self.audio_thread.is_alive()):
                self._start_audio_streaming()
            
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
    
    def stop_transcription(self, suppress_output: bool = False, final_quiet_ms: int = 600, max_wait_ms: int = 1800):
        """Stop the transcription session."""
        print("\n🛑 Stopping audio streaming...")

        # On shutdown, suppress output FIRST to prevent any last-millisecond injections
        # from WS messages arriving concurrently with teardown.
        self._suppress_output = bool(suppress_output)
        if suppress_output:
            try:
                # Hard-stop typing and clear any queued work immediately
                if hasattr(self.injector, "flush_and_clear"):
                    self.injector.flush_and_clear()
                elif hasattr(self.injector, "disable"):
                    self.injector.disable()
                else:
                    self.injector.stop()
            except Exception:
                pass

        # Signal stop audio streaming but keep WebSocket open momentarily
        self.stop_event.set()
        
        # Wait for audio streaming to stop
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        
        # Cleanup audio first
        self._cleanup_audio()
        
        # On normal release, wait for a short quiet period to capture final words
        if not suppress_output:
            print("⏱️  Waiting for final transcription (quiet period)...")
            start_wait = time.time()
            max_wait_s = max_wait_ms / 1000.0
            quiet_s = final_quiet_ms / 1000.0
            while (time.time() - start_wait) < max_wait_s:
                if (time.time() - self._last_ws_msg_time) >= quiet_s:
                    break
                time.sleep(0.05)
        
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
        try:
            # Stop worker and drop any stale queue
            self.injector.stop()
        except Exception:
            pass
        
        # Show session summary
        if hasattr(self, 'total_characters_typed') and self.total_characters_typed > 0:
            print(f"📊 Session summary: {self.total_characters_typed} characters typed total")
            print(f"📝 Full session text: '{getattr(self, 'session_text', '')}'")
        
        # Reset tracking for next session
        self.total_characters_typed = 0
        self.turn_count = 0
        self.session_text = ""
        self.stop_event.clear()  # Reset for next session
        
        # Reset audio cleanup flag for next session
        with self._audio_cleanup_lock:
            self._audio_cleaned_up = False
        
        self.state = TranscriptionState.IDLE
        print("✅ Transcription stopped")

    def quiesce_output(self):
        """Prevent any further keystroke injection immediately."""
        self._suppress_output = True
        try:
            # Emergency flush to prevent spurious output on shutdown
            if hasattr(self.injector, "flush_and_clear"):
                self.injector.flush_and_clear()
            # Disable accepts and invalidate any in-flight or queued items
            elif hasattr(self.injector, "disable"):
                self.injector.disable()
            else:
                self.injector.stop()
            # Ensure no in-flight injection remains
            try:
                if hasattr(self.injector, "wait_idle"):
                    self.injector.wait_idle(timeout=1.0)
            except Exception:
                pass
        except Exception:
            pass
    
    def _cleanup_audio(self):
        """Clean up audio resources - thread-safe and idempotent."""
        with self._audio_cleanup_lock:
            # Check if already cleaned up
            if self._audio_cleaned_up:
                return
            
            # Mark as cleaned up first to prevent race conditions
            self._audio_cleaned_up = True
            
            # Clean up audio stream
            if self.audio_stream:
                try:
                    # Check if stream is active before stopping
                    if self.audio_stream.is_active():
                        try:
                            self.audio_stream.stop_stream()
                        except Exception as e:
                            print(f"⚠️ Error stopping audio stream: {e}")
                    
                    # Close the stream
                    try:
                        self.audio_stream.close()
                    except Exception as e:
                        print(f"⚠️ Error closing audio stream: {e}")
                    
                except Exception as e:
                    print(f"⚠️ Error during audio cleanup: {e}")
                finally:
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
        
        # Keybind manager (default) and Quartz fallback
        self.kbm: Optional[PTTKeybindManager] = None
        self.quartz_listener: Optional[EventTapPTTListener] = None
        self.keyboard_listener: Optional[keyboard.Listener] = None  # legacy; no longer used
        
        # Create PTT keybind from config
        ptt_config = self.config.get("keybinds", {}).get("ptt", "leftshift+rightshift")
        if ptt_config == "leftshift+rightshift":
            self.ptt_keybind = PTTKeybind(
                modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
            )
        else:
            # Try to parse from config string  
            if hasattr(PTTKeybindManager(), 'create_keybind_from_string'):
                temp_manager = PTTKeybindManager()
                parsed_keybind = temp_manager.create_keybind_from_string(ptt_config)
                self.ptt_keybind = parsed_keybind if parsed_keybind else PTTKeybind(
                    modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
                )
            else:
                # Fallback to default
                self.ptt_keybind = PTTKeybind(
                    modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
                )
        self.ptt_active = False
        self.ptt_pressed_at: Optional[float] = None
        # Listener watchdog to ensure long-running reliability
        self.listener_watchdog_thread: Optional[threading.Thread] = None
        self.listener_watchdog_stop = threading.Event()
        self.listener_restart_lock = threading.Lock()
        self.shutting_down = threading.Event()
        self.cleanup_started = threading.Event()
        
        # PTT indicator (visual feedback)
        indicator_config = self.config.get("indicator", {})
        if indicator_config.get("enabled", True):
            self.indicator: Optional[PTTIndicator] = create_indicator(indicator_config)
            print("🔴 PTT indicator enabled")
        else:
            self.indicator = None
        
        print(f"🔧 PTT Keybind configured: {ptt_config}")
        print(f"🔧 Parsed modifiers: {self.ptt_keybind.modifiers}")
        
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
        """Configure push-to-talk keybind using PTTKeybindManager with watchdog."""
        print("📍 Push-to-Talk configured: Both Shift Keys (left + right)")
        print(f"   Keybind modifiers: {self.ptt_keybind.modifiers}")
        # Start keybind manager
        try:
            self.kbm = PTTKeybindManager()
            self.kbm.register_ptt(self.ptt_keybind, self._on_ptt_press, self._on_ptt_release)
            self.kbm.start()
            print("🔁 PTTKeybindManager started")
        except Exception as e:
            print(f"❌ Failed to start PTTKeybindManager: {e}")
        # Start Quartz event tap listener (always require both left + right shift)
        try:
            self.quartz_listener = EventTapPTTListener(
                self._on_ptt_press, self._on_ptt_release, require_left_right_shift=True
            )
            self.quartz_listener.start()
            print("🧲 Quartz event tap listener started (requires L+R Shift)")
        except Exception as e:
            print(f"⚠️ Failed to start Quartz event tap listener: {e}")
        # Start watchdog
        if not self.listener_watchdog_thread or not self.listener_watchdog_thread.is_alive():
            self.listener_watchdog_stop.clear()
            self.listener_watchdog_thread = threading.Thread(target=self._watch_keyboard_listener, daemon=True)
            self.listener_watchdog_thread.start()

    def _restart_key_listener(self):
        with self.listener_restart_lock:
            try:
                if self.kbm:
                    self.kbm.stop()
            except Exception:
                pass
            try:
                if self.kbm:
                    self.kbm.reset_state()
                    self.kbm.start()
                    print("🔁 Key listener restarted")
            except Exception as e:
                print(f"❌ Failed to restart key listener: {e}")

    def _watch_keyboard_listener(self):
        """Watchdog that restarts the keyboard listener if it dies and handles stuck PTT."""
        stuck_threshold_s = 90.0
        check_interval = 3.0  # Check more frequently
        last_quartz_restart = 0
        
        while not self.listener_watchdog_stop.is_set():
            time.sleep(check_interval)
            try:
                # Restart if listener missing or not running
                if (self.kbm is None) or (self.kbm.listener is None) or (not getattr(self.kbm.listener, 'running', False)):
                    print("⚠️ Keyboard listener not running; attempting restart...")
                    self._restart_key_listener()
                
                # Check Quartz listener more aggressively
                if self.quartz_listener:
                    # Always try to ensure it's running
                    if not self.quartz_listener.is_running():
                        try:
                            print("⚠️ Quartz listener not running; attempting restart...")
                            self.quartz_listener.stop()  # Clean stop first
                            time.sleep(0.1)
                            self.quartz_listener.start()
                            last_quartz_restart = time.time()
                        except Exception as e:
                            print(f"⚠️ Failed to restart Quartz listener: {e}")
                            # Try creating a new instance
                            try:
                                self.quartz_listener = EventTapPTTListener(
                                    self._on_ptt_press, 
                                    self._on_ptt_release, 
                                    require_left_right_shift=True
                                )
                                self.quartz_listener.start()
                                print("✅ Created new Quartz listener instance")
                            except Exception as e2:
                                print(f"❌ Failed to create new Quartz listener: {e2}")
                    
                    # Periodically restart Quartz listener as preventive measure
                    elif (time.time() - last_quartz_restart) > 300:  # Every 5 minutes
                        try:
                            print("🔄 Preventive Quartz listener restart...")
                            self.quartz_listener.stop()
                            time.sleep(0.1)
                            self.quartz_listener.start()
                            last_quartz_restart = time.time()
                        except Exception:
                            pass
                
                # Stuck PTT guard
                if self.ptt_active and self.ptt_pressed_at is not None:
                    if (time.time() - self.ptt_pressed_at) > stuck_threshold_s:
                        print("⚠️ PTT appears stuck; forcing release and resetting listener state")
                        try:
                            self._on_ptt_release()
                        except Exception:
                            pass
                        try:
                            if self.kbm:
                                self.kbm.reset_state()
                        except Exception:
                            pass
                        self.ptt_active = False
                        self.ptt_pressed_at = None
                        
                        # Also restart listeners after stuck PTT
                        self._restart_key_listener()
                        if self.quartz_listener:
                            try:
                                self.quartz_listener.stop()
                                time.sleep(0.1)
                                self.quartz_listener.start()
                            except Exception:
                                pass
            except Exception as e:
                print(f"⚠️ Keyboard listener watchdog error: {e}")
    
    
    def _on_ptt_press(self):
        """Handle PTT key press (start transcription)."""
        if self.shutting_down.is_set() or self.ptt_active:
            return
        
        print("\n" + "="*60)
        print("🎤 PTT PRESSED - Recording...")
        print("💡 Text will appear at your cursor position!")
        print("="*60)
        
        self.ptt_pressed_at = time.time()
        self.ptt_active = True
        
        # Show indicator
        if self.indicator:
            try:
                self.indicator.show_active()
            except Exception:
                pass
        
        if not self.is_transcribing:
            self._start_transcription()
    
    def _on_ptt_release(self):
        """Handle PTT key release (stop transcription)."""
        if self.shutting_down.is_set() or not self.ptt_active:
            return
            
        print("\n" + "="*60)
        print("🔴 PTT RELEASED - Stopping...")
        print("="*60)
        
        self.ptt_pressed_at = None
        self.ptt_active = False
        
        # Hide indicator
        if self.indicator:
            try:
                self.indicator.show_idle()
            except Exception:
                pass
        
        if self.is_transcribing:
            # Normal PTT release: don't suppress output; allow quiet-period
            self._stop_transcription(suppress_output=False)
    
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
            # Audio tuning from config
            audio_cfg = cfg.get("audio", {}) if isinstance(cfg, dict) else {}
            chunk_duration_ms_cfg = audio_cfg.get("chunk_duration_ms")
            min_send_ms_cfg = audio_cfg.get("min_send_ms")
            prebuffer_ms_cfg = audio_cfg.get("prebuffer_ms")

            self.transcriber = PTTTranscriber(
                ai_config,
                word_replacements=word_replacements,
                joiner_values=joiner_values,
                phrase_replacements=phrase_replacements,
                audio_chunk_duration_ms=chunk_duration_ms_cfg,
                min_send_ms=min_send_ms_cfg,
                prebuffer_ms=prebuffer_ms_cfg,
                typing_mode=(self.config.get("typing", {}) or {}).get("mode"),
                preserve_clipboard=(self.config.get("typing", {}) or {}).get("preserve_clipboard"),
            )
            
            # Adjust typing delay if configured
            if "typing" in self.config:
                self.transcriber.injector.typing_delay = self.config["typing"].get(
                    "delay_ms", 5
                ) / 1000
                # Optional: allow switching injection mode
                try:
                    mode = self.config["typing"].get("mode")
                    if mode:
                        self.transcriber.injector.mode = str(mode).strip().lower()  # type: ignore[attr-defined]
                except Exception:
                    pass
            
            # Start transcription
            self.transcriber.start_transcription()
            
        except Exception as e:
            print(f"❌ Failed to start transcription: {e}")
            import traceback
            traceback.print_exc()
            self.is_transcribing = False
    
    def _stop_transcription(self, suppress_output: bool = False, final_quiet_ms: Optional[int] = None, max_wait_ms: Optional[int] = None):
        """Stop the transcription session."""
        if not self.is_transcribing or not self.transcriber:
            return
        
        # Stop the transcriber
        if self.transcriber:
            # Pull quiet-period settings from config if not explicitly provided
            cfg_session = self.config.get("session", {}) if isinstance(self.config, dict) else {}
            fq = final_quiet_ms if final_quiet_ms is not None else cfg_session.get("final_quiet_ms", 800)
            mw = max_wait_ms if max_wait_ms is not None else cfg_session.get("max_final_wait_ms", 2500)
            self.transcriber.stop_transcription(
                suppress_output=suppress_output,
                final_quiet_ms=int(fq),
                max_wait_ms=int(mw),
            )
        
        # Clean up
        self.transcriber = None
        self.is_transcribing = False
        
        print("✅ Ready for next PTT press")
    
    def cleanup(self):
        """Cleanup all resources."""
        if self.cleanup_started.is_set():
            return
        self.cleanup_started.set()
        print("\n🔄 Cleaning up...")
        # Block any further PTT callbacks
        self.shutting_down.set()
        # Emergency flush any queued typing to prevent spurious output
        try:
            if self.transcriber and hasattr(self.transcriber, 'injector'):
                self.transcriber.injector.flush_and_clear()
        except Exception:
            pass
        
        # Quiesce any output immediately
        try:
            if self.transcriber:
                self.transcriber.quiesce_output()
        except Exception:
            pass
        
        # Stop transcription if active
        if self.is_transcribing:
            # Suppress output during full app shutdown
            self._stop_transcription(suppress_output=True)
        
        # First stop watchdog to avoid restarts during shutdown
        self.listener_watchdog_stop.set()
        if self.listener_watchdog_thread and self.listener_watchdog_thread.is_alive():
            try:
                self.listener_watchdog_thread.join(timeout=1.0)
            except Exception:
                pass
        
        # Then stop listeners cleanly
        try:
            if self.quartz_listener:
                print("🧲 Stopping Quartz event tap listener...")
                self.quartz_listener.stop()
        except Exception:
            pass
        try:
            if self.kbm:
                print("⌨️  Stopping keybind manager...")
                self.kbm.stop()
        except Exception:
            pass
        
        # Cleanup transcriber
        if self.transcriber:
            self.transcriber.cleanup()
        
        # Cleanup indicator
        if self.indicator:
            try:
                self.indicator.cleanup()
            except Exception:
                pass
        
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

        # Initialize indicator on main thread (Cocoa requirement)
        if self.indicator:
            try:
                self.indicator.initialize()
            except Exception as e:
                print(f"⚠️ Failed to initialize indicator: {e}")
        
        # Keep running until interrupted
        try:
            while True:
                # Pump indicator run loop so the overlay can render/update
                if self.indicator:
                    try:
                        self.indicator.pump(max_step_s=0.01)
                    except Exception:
                        pass
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

    # Install signal handlers to quiesce output immediately on interrupt/terminate
    def _handle_signal(signum, _frame):
        try:
            print(f"\n⚠️  Signal {signum} received - shutting down...")
        except Exception:
            pass
        try:
            app.shutting_down.set()
        except Exception:
            pass
        try:
            if getattr(app, 'transcriber', None):
                if hasattr(app.transcriber, 'injector'):
                    app.transcriber.injector.flush_and_clear()
                app.transcriber.quiesce_output()
        except Exception:
            pass
        try:
            app.cleanup()
            # Give the OS a moment to drain any already-posted HID events; without this
            # you can see a "burst" of queued characters after Ctrl+C.
            try:
                time.sleep(0.25)
            except Exception:
                pass
        finally:
            try:
                sys.exit(128 + signum)
            except SystemExit:
                raise

    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGQUIT, _handle_signal)
    except Exception:
        pass
    
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