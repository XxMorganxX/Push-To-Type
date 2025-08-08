#!/usr/bin/env python3
"""Debug script to see exactly how shift keys are reported by pynput."""

from pynput import keyboard
import time

pressed_keys = set()
press_log = []
release_log = []

def on_press(key):
    """Handle key press events."""
    timestamp = time.time()
    pressed_keys.add(key)
    
    log_entry = f"{timestamp:.3f}: PRESS {key} (type: {type(key).__name__})"
    
    # Check key identity
    if hasattr(keyboard.Key, 'shift'):
        if key == keyboard.Key.shift:
            log_entry += " [GENERIC SHIFT]"
    if hasattr(keyboard.Key, 'shift_l'):
        if key == keyboard.Key.shift_l:
            log_entry += " [LEFT SHIFT]"
    if hasattr(keyboard.Key, 'shift_r'):
        if key == keyboard.Key.shift_r:
            log_entry += " [RIGHT SHIFT]"
    
    print(f"🟢 {log_entry}")
    print(f"   Pressed keys now: {pressed_keys}")
    press_log.append(log_entry)

def on_release(key):
    """Handle key release events."""
    timestamp = time.time()
    
    log_entry = f"{timestamp:.3f}: RELEASE {key} (type: {type(key).__name__})"
    
    # Check key identity
    if hasattr(keyboard.Key, 'shift'):
        if key == keyboard.Key.shift:
            log_entry += " [GENERIC SHIFT]"
    if hasattr(keyboard.Key, 'shift_l'):
        if key == keyboard.Key.shift_l:
            log_entry += " [LEFT SHIFT]"
    if hasattr(keyboard.Key, 'shift_r'):
        if key == keyboard.Key.shift_r:
            log_entry += " [RIGHT SHIFT]"
    
    print(f"🔴 {log_entry}")
    
    # Show what's in pressed_keys before removal
    print(f"   Before removal: {pressed_keys}")
    
    # Try to remove the key
    if key in pressed_keys:
        pressed_keys.remove(key)
        print(f"   Successfully removed {key}")
    else:
        print(f"   ⚠️  KEY NOT IN SET! Cannot remove {key}")
        # Check if a different variant is in the set
        if key == keyboard.Key.shift:
            if keyboard.Key.shift_l in pressed_keys:
                print(f"      Found shift_l in set, removing it")
                pressed_keys.remove(keyboard.Key.shift_l)
            if keyboard.Key.shift_r in pressed_keys:
                print(f"      Found shift_r in set, removing it")
                pressed_keys.remove(keyboard.Key.shift_r)
        elif key == keyboard.Key.shift_l:
            if keyboard.Key.shift in pressed_keys:
                print(f"      Found generic shift in set, removing it")
                pressed_keys.remove(keyboard.Key.shift)
        elif key == keyboard.Key.shift_r:
            if keyboard.Key.shift in pressed_keys:
                print(f"      Found generic shift in set, removing it")
                pressed_keys.remove(keyboard.Key.shift)
    
    print(f"   After removal: {pressed_keys}")
    release_log.append(log_entry)
    
    if key == keyboard.Key.esc:
        return False

def main():
    print("="*60)
    print("SHIFT KEY DEBUG")
    print("="*60)
    print("\nInstructions:")
    print("1. Press LEFT SHIFT - observe the output")
    print("2. Press RIGHT SHIFT while holding LEFT - observe the output")
    print("3. Release RIGHT SHIFT - observe the output")
    print("4. Release LEFT SHIFT - observe the output")
    print("\nPress ESC to exit\n")
    print("-"*60)
    
    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:
        listener.join()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("\nPress events:")
    for entry in press_log:
        print(f"  {entry}")
    print("\nRelease events:")
    for entry in release_log:
        print(f"  {entry}")

if __name__ == "__main__":
    main()