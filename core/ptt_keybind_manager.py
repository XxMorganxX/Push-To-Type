import time
import threading
from typing import Dict, Set, Callable, Optional, Tuple
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
    
    def matches(self, pressed_keys: Set, current_key) -> bool:
        """Check if current pressed keys match this keybind."""
        # For modifier-only keybinds (like leftshift+rightshift), we need EXACT match
        if not self.key and not self.char:
            # All required modifiers must be pressed
            if not all(mod in pressed_keys for mod in self.modifiers):
                return False
            # Current key must be one of the required modifiers
            if current_key not in self.modifiers:
                return False
            # All modifiers must now be present
            return all(mod in pressed_keys for mod in self.modifiers)
        
        # For keybinds with a trigger key
        # Check if all required modifiers are pressed
        if not all(mod in pressed_keys for mod in self.modifiers):
            return False
        
        # Check if the trigger key matches
        if self.key and current_key == self.key:
            return True
        if self.char and hasattr(current_key, 'char') and current_key.char == self.char:
            return True
            
        return False
    
    def is_still_held(self, pressed_keys: Set) -> bool:
        """Check if the keybind is still being held."""
        # For modifier-only keybinds, all modifiers must still be pressed
        if not self.key and not self.char:
            return all(mod in pressed_keys for mod in self.modifiers)
        
        # For keybinds with trigger keys, all modifiers must still be pressed
        return all(mod in pressed_keys for mod in self.modifiers)


class PTTKeybindManager:
    """
    Push-to-Talk keybind manager that triggers on press and release.
    """
    
    def __init__(self):
        """Initialize the PTT keybind manager."""
        self.ptt_keybind: Optional[PTTKeybind] = None
        self.on_press_callback: Optional[Callable] = None
        self.on_release_callback: Optional[Callable] = None
        
        self.pressed_keys: Set = set()
        self.ptt_state = PTTState.IDLE
        self.listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        
        # Track the specific key combination that triggered PTT
        self.active_trigger_keys: Set = set()
        
        # Track shift keys specifically for better handling
        self.left_shift_pressed = False
        self.right_shift_pressed = False
        
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
        with self._lock:
            self.pressed_keys.clear()
            self.active_trigger_keys.clear()
            self.ptt_state = PTTState.IDLE
            self.left_shift_pressed = False
            self.right_shift_pressed = False
    
    def _on_press(self, key):
        """Handle key press events."""
        self._last_event_time = time.time()
        
        with self._lock:
            # Track shift keys specifically
            if key in (keyboard.Key.shift_l, keyboard.Key.shift):
                self.left_shift_pressed = True
            elif key == keyboard.Key.shift_r:
                self.right_shift_pressed = True
            
            # Add key to pressed set
            self.pressed_keys.add(key)
            
            # Only trigger if not already pressed
            if self.ptt_state == PTTState.IDLE:
                # Special handling for left+right shift combination
                if (self.ptt_keybind and 
                    keyboard.Key.shift_l in self.ptt_keybind.modifiers and 
                    keyboard.Key.shift_r in self.ptt_keybind.modifiers):
                    # Check if both shifts are pressed
                    if self.left_shift_pressed and self.right_shift_pressed:
                        self.active_trigger_keys = {keyboard.Key.shift_l, keyboard.Key.shift_r}
                        self._trigger_press()
                elif self.ptt_keybind and self.ptt_keybind.matches(self.pressed_keys, key):
                    # Record which keys triggered the PTT
                    self.active_trigger_keys = self.pressed_keys.copy()
                    self._trigger_press()
    
    def _on_release(self, key):
        """Handle key release events."""
        self._last_event_time = time.time()
        
        with self._lock:
            # Track shift key releases
            shift_released = False
            if key in (keyboard.Key.shift_l, keyboard.Key.shift):
                self.left_shift_pressed = False
                shift_released = True
            elif key == keyboard.Key.shift_r:
                self.right_shift_pressed = False
                shift_released = True
            
            # Remove key from pressed set
            self.pressed_keys.discard(key)
            # Also remove generic shift if a specific shift is released
            if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
                self.pressed_keys.discard(keyboard.Key.shift)
            # Also remove specific shifts if generic shift is released
            elif key == keyboard.Key.shift:
                self.pressed_keys.discard(keyboard.Key.shift_l)
                self.pressed_keys.discard(keyboard.Key.shift_r)
            
            # Check if PTT should be released
            if self.ptt_state == PTTState.PRESSED:
                # Special handling for left+right shift combination
                if (self.ptt_keybind and 
                    keyboard.Key.shift_l in self.ptt_keybind.modifiers and 
                    keyboard.Key.shift_r in self.ptt_keybind.modifiers):
                    # Release if either shift is released
                    if shift_released and (not self.left_shift_pressed or not self.right_shift_pressed):
                        self._trigger_release()
                # For other keybinds, use standard logic
                elif key in self.active_trigger_keys:
                    self._trigger_release()
                elif not self.ptt_keybind.is_still_held(self.pressed_keys):
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
        self.active_trigger_keys.clear()
        
        if self.on_release_callback:
            # Run callback in separate thread to avoid blocking
            def run_callback():
                try:
                    self.on_release_callback()
                except Exception as e:
                    print(f"Error in PTT release callback: {e}")
                finally:
                    # Reset to idle after release is processed
                    with self._lock:
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