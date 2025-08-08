import time
import threading
from typing import Callable, Optional, Set
from pynput import keyboard
from dataclasses import dataclass
from enum import Enum


class PTTState(Enum):
    """States for push-to-talk."""
    IDLE = "idle"
    PRESSED = "pressed"
    RELEASED = "released"


@dataclass
class PTTKeybind:
    """Represents a push-to-talk keybind."""
    modifiers: Set[keyboard.Key]
    key: Optional[keyboard.Key] = None
    char: Optional[str] = None


class PTTKeybindManager:
    """
    Push-to-Talk keybind manager that triggers on press and release.
    Uses a cleaner implementation based on the provided example.
    """
    
    def __init__(self):
        """Initialize the PTT keybind manager."""
        self.ptt_keybind: Optional[PTTKeybind] = None
        self.on_press_callback: Optional[Callable] = None
        self.on_release_callback: Optional[Callable] = None
        
        self.listener: Optional[keyboard.Listener] = None
        self.ptt_state = PTTState.IDLE
        
        # Track shift keys using simple string identifiers
        self.pressed_shifts: Set[str] = set()
        self.has_triggered_for_current_combo = False
        
        # Constants for clarity
        self.LEFT = "left"
        self.RIGHT = "right"
        
        # Auto-recovery monitoring
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        self._last_event_time = time.time()
        
    def register_ptt(self, keybind: PTTKeybind, 
                    on_press: Callable, 
                    on_release: Callable):
        """
        Register push-to-talk callbacks.
        
        Args:
            keybind: PTT keybind configuration
            on_press: Function to call when PTT is pressed
            on_release: Function to call when PTT is released
        """
        self.ptt_keybind = keybind
        self.on_press_callback = on_press
        self.on_release_callback = on_release
    
    def start(self):
        """Start listening for keyboard events."""
        if self.listener:
            self.stop()
            
        self._last_event_time = time.time()
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()
        
        # Start monitor thread
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._stop_monitor.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_listener, daemon=True)
            self._monitor_thread.start()
    
    def stop(self):
        """Stop listening for keyboard events."""
        self._stop_monitor.set()
        
        if self.listener:
            # If PTT is active, release it first
            if self.ptt_state == PTTState.PRESSED:
                self._trigger_release()
            
            self.listener.stop()
            self.listener = None
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        
        self.reset_state()
    
    def reset_state(self):
        """Reset the internal state."""
        self.pressed_shifts.clear()
        self.has_triggered_for_current_combo = False
        self.ptt_state = PTTState.IDLE
    
    def _is_left_shift(self, key) -> bool:
        """Check if key is left shift."""
        left_shift_key = getattr(keyboard.Key, "shift_l", None)
        return left_shift_key is not None and key == left_shift_key
    
    def _is_right_shift(self, key) -> bool:
        """Check if key is right shift."""
        right_shift_key = getattr(keyboard.Key, "shift_r", None)
        return right_shift_key is not None and key == right_shift_key
    
    def _on_press(self, key):
        """Handle key press events - clean implementation."""
        self._last_event_time = time.time()
        
        # Ignore generic Key.shift on press; require side-specific keys
        if self._is_left_shift(key):
            self.pressed_shifts.add(self.LEFT)
        elif self._is_right_shift(key):
            self.pressed_shifts.add(self.RIGHT)
        
        # Check if both shifts are pressed and we haven't triggered yet
        if (self.LEFT in self.pressed_shifts and 
            self.RIGHT in self.pressed_shifts and 
            not self.has_triggered_for_current_combo):
            
            self.has_triggered_for_current_combo = True
            self._trigger_press()
    
    def _on_release(self, key):
        """Handle key release events - clean implementation."""
        self._last_event_time = time.time()
        
        released_any = False
        
        # If we get a generic Shift release, clear both to avoid stuck state
        if key == keyboard.Key.shift:
            if self.pressed_shifts:
                self.pressed_shifts.clear()
                released_any = True
        elif self._is_left_shift(key):
            if self.LEFT in self.pressed_shifts:
                self.pressed_shifts.discard(self.LEFT)
                released_any = True
        elif self._is_right_shift(key):
            if self.RIGHT in self.pressed_shifts:
                self.pressed_shifts.discard(self.RIGHT)
                released_any = True
        
        if released_any:
            # Allow triggering again on the next time both are held
            self.has_triggered_for_current_combo = False
            
            # If we were in pressed state, trigger release
            if self.ptt_state == PTTState.PRESSED:
                self._trigger_release()
    
    def _trigger_press(self):
        """Trigger PTT press callback."""
        if self.ptt_state != PTTState.IDLE:
            return
            
        self.ptt_state = PTTState.PRESSED
        
        if self.on_press_callback:
            # Run callback in separate thread to avoid blocking
            def run_callback():
                try:
                    self.on_press_callback()
                except Exception as e:
                    print(f"Error in PTT press callback: {e}")
            
            threading.Thread(target=run_callback, daemon=True).start()
    
    def _trigger_release(self):
        """Trigger PTT release callback."""
        if self.ptt_state != PTTState.PRESSED:
            return
            
        self.ptt_state = PTTState.RELEASED
        
        if self.on_release_callback:
            # Run callback in separate thread to avoid blocking
            def run_callback():
                try:
                    self.on_release_callback()
                except Exception as e:
                    print(f"Error in PTT release callback: {e}")
                finally:
                    # Reset to idle after release is processed
                    self.ptt_state = PTTState.IDLE
            
            threading.Thread(target=run_callback, daemon=True).start()
        else:
            self.ptt_state = PTTState.IDLE
    
    def is_pressed(self) -> bool:
        """Check if PTT is currently pressed."""
        return self.ptt_state == PTTState.PRESSED
    
    def create_keybind_from_string(self, keybind_str: str) -> Optional[PTTKeybind]:
        """
        Create a PTTKeybind object from a string representation.
        
        Args:
            keybind_str: String like "cmd+shift+space" or "leftshift+rightshift"
            
        Returns:
            PTTKeybind object or None if parsing fails
        """
        parts = keybind_str.lower().split('+')
        modifiers = set()
        key = None
        char = None
        
        key_mapping = {
            'cmd': keyboard.Key.cmd,
            'command': keyboard.Key.cmd,
            'ctrl': keyboard.Key.ctrl,
            'control': keyboard.Key.ctrl,
            'alt': keyboard.Key.alt,
            'option': keyboard.Key.alt,
            'shift': keyboard.Key.shift,
            'leftshift': keyboard.Key.shift_l,
            'rightshift': keyboard.Key.shift_r,
            'space': keyboard.Key.space,
            'tab': keyboard.Key.tab,
            'enter': keyboard.Key.enter,
            'return': keyboard.Key.enter,
            'esc': keyboard.Key.esc,
            'escape': keyboard.Key.esc,
        }
        
        for part in parts:
            if part in key_mapping:
                mapped_key = key_mapping[part]
                if mapped_key in [keyboard.Key.cmd, keyboard.Key.ctrl, 
                                 keyboard.Key.alt, keyboard.Key.shift,
                                 keyboard.Key.shift_l, keyboard.Key.shift_r]:
                    modifiers.add(mapped_key)
                else:
                    key = mapped_key
            elif len(part) == 1:
                char = part
        
        if not modifiers:
            return None
            
        return PTTKeybind(modifiers=modifiers, key=key, char=char)
    
    def _monitor_listener(self):
        """Monitor thread that ensures the listener stays active."""
        while not self._stop_monitor.is_set():
            time.sleep(2.0)  # Check every 2 seconds
            
            try:
                # Check if listener is dead
                if self.listener and not getattr(self.listener, 'running', False):
                    print("⚠️ PTTKeybindManager: Listener died, restarting...")
                    self.listener = keyboard.Listener(
                        on_press=self._on_press,
                        on_release=self._on_release
                    )
                    self.listener.start()
                    self._last_event_time = time.time()
                    print("✅ PTTKeybindManager: Listener restarted")
                
                # Check for stale events (no events in 60+ seconds might indicate issues)
                time_since_last = time.time() - self._last_event_time
                if time_since_last > 60 and self.listener:
                    print(f"🔄 PTTKeybindManager: No events for {time_since_last:.1f}s, restarting listener...")
                    try:
                        self.listener.stop()
                    except Exception:
                        pass
                    
                    self.listener = keyboard.Listener(
                        on_press=self._on_press,
                        on_release=self._on_release
                    )
                    self.listener.start()
                    self._last_event_time = time.time()
                    print("✅ PTTKeybindManager: Listener refreshed")
                    
            except Exception as e:
                print(f"⚠️ PTTKeybindManager monitor error: {e}")