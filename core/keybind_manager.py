import time
import threading
from typing import Dict, Set, Callable, Optional, Tuple
from pynput import keyboard
from dataclasses import dataclass
from enum import Enum


class KeybindState(Enum):
    """States for keybind detection."""
    IDLE = "idle"
    PRESSED = "pressed"
    COOLDOWN = "cooldown"


@dataclass
class Keybind:
    """Represents a keyboard combination."""
    modifiers: Set[keyboard.Key]
    key: Optional[keyboard.Key] = None
    char: Optional[str] = None
    
    def matches(self, pressed_keys: Set, current_key) -> bool:
        """Check if current pressed keys match this keybind."""
        # Check if all required modifiers are pressed
        if not all(mod in pressed_keys for mod in self.modifiers):
            return False
        
        # Check if the trigger key matches
        if self.key and current_key == self.key:
            return True
        if self.char and hasattr(current_key, 'char') and current_key.char == self.char:
            return True
            
        return False
    
    def __str__(self) -> str:
        """String representation of the keybind."""
        parts = [str(mod).replace('Key.', '') for mod in self.modifiers]
        if self.key:
            parts.append(str(self.key).replace('Key.', ''))
        elif self.char:
            parts.append(self.char)
        return '+'.join(parts)


class KeybindManager:
    """
    Manages keyboard shortcuts with strict combination detection and state management.
    """
    
    def __init__(self, cooldown_time: float = 0.5):
        """
        Initialize the keybind manager.
        
        Args:
            cooldown_time: Time in seconds before keybind can be triggered again
        """
        self.cooldown_time = cooldown_time
        self.keybinds: Dict[str, Tuple[Keybind, Callable]] = {}
        self.pressed_keys: Set = set()
        self.state = KeybindState.IDLE
        self.last_trigger_time = 0
        self.listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        
    def register_keybind(self, name: str, keybind: Keybind, callback: Callable):
        """
        Register a new keybind with its callback.
        
        Args:
            name: Unique name for the keybind
            keybind: Keybind configuration
            callback: Function to call when keybind is triggered
        """
        self.keybinds[name] = (keybind, callback)
        
    def unregister_keybind(self, name: str):
        """
        Remove a registered keybind.
        
        Args:
            name: Name of the keybind to remove
        """
        if name in self.keybinds:
            del self.keybinds[name]
    
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
            self.listener.stop()
            self.listener = None
        self.reset_state()
    
    def reset_state(self):
        """Reset the internal state."""
        with self._lock:
            self.pressed_keys.clear()
            self.state = KeybindState.IDLE
    
    def _on_press(self, key):
        """Handle key press events."""
        with self._lock:
            # Add key to pressed set
            self.pressed_keys.add(key)
            
            # Check if in cooldown
            if self.state == KeybindState.COOLDOWN:
                if time.time() - self.last_trigger_time < self.cooldown_time:
                    return
                else:
                    self.state = KeybindState.IDLE
            
            # Check all registered keybinds
            for name, (keybind, callback) in self.keybinds.items():
                if keybind.matches(self.pressed_keys, key):
                    self._trigger_keybind(name, callback)
                    break
    
    def _on_release(self, key):
        """Handle key release events."""
        with self._lock:
            self.pressed_keys.discard(key)
            
            # Reset state if all keys released
            if not self.pressed_keys and self.state == KeybindState.PRESSED:
                self.state = KeybindState.COOLDOWN
                self.last_trigger_time = time.time()
    
    def _trigger_keybind(self, name: str, callback: Callable):
        """
        Trigger a keybind callback.
        
        Args:
            name: Name of the triggered keybind
            callback: Callback function to execute
        """
        if self.state != KeybindState.IDLE:
            return
            
        self.state = KeybindState.PRESSED
        
        # Run callback in separate thread to avoid blocking
        def run_callback():
            try:
                callback()
            except Exception as e:
                print(f"Error in keybind '{name}' callback: {e}")
        
        threading.Thread(target=run_callback, daemon=True).start()
    
    def create_keybind_from_string(self, keybind_str: str) -> Optional[Keybind]:
        """
        Create a Keybind object from a string representation.
        
        Args:
            keybind_str: String like "cmd+shift+space" or "ctrl+alt+t"
            
        Returns:
            Keybind object or None if parsing fails
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
                                 keyboard.Key.alt, keyboard.Key.shift]:
                    modifiers.add(mapped_key)
                else:
                    key = mapped_key
            elif len(part) == 1:
                char = part
        
        if not modifiers:
            return None
            
        return Keybind(modifiers=modifiers, key=key, char=char)