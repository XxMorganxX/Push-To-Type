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
            # Must have exactly the required modifiers and current key must be one of them
            return (self.modifiers == pressed_keys and 
                    current_key in self.modifiers)
        
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
        # For modifier-only keybinds, require exact match
        if not self.key and not self.char:
            return self.modifiers == pressed_keys
        
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
            
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()
    
    def stop(self):
        """Stop listening for keyboard events."""
        if self.listener:
            # If PTT is active, release it first
            if self.ptt_state == PTTState.PRESSED:
                self._trigger_release()
            
            self.listener.stop()
            self.listener = None
        self.reset_state()
    
    def reset_state(self):
        """Reset the internal state."""
        with self._lock:
            self.pressed_keys.clear()
            self.active_trigger_keys.clear()
            self.ptt_state = PTTState.IDLE
    
    def _on_press(self, key):
        """Handle key press events."""
        with self._lock:
            # Add key to pressed set
            self.pressed_keys.add(key)
            
            # Only trigger if not already pressed
            if self.ptt_state == PTTState.IDLE:
                if self.ptt_keybind and self.ptt_keybind.matches(self.pressed_keys, key):
                    # Record which keys triggered the PTT
                    self.active_trigger_keys = self.pressed_keys.copy()
                    self._trigger_press()
    
    def _on_release(self, key):
        """Handle key release events."""
        with self._lock:
            # Remove key from pressed set
            self.pressed_keys.discard(key)
            
            # Check if PTT should be released
            if self.ptt_state == PTTState.PRESSED:
                # Release if any of the trigger keys are released
                if key in self.active_trigger_keys:
                    self._trigger_release()
                # Also release if the keybind is no longer satisfied
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