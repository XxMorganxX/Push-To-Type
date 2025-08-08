#!/usr/bin/env python3
"""Test script to debug shift key release detection."""

import time
from pynput import keyboard

# Track pressed keys
pressed_keys = set()

def on_press(key):
    """Handle key press events."""
    pressed_keys.add(key)
    
    # Check for both shift keys
    if keyboard.Key.shift_l in pressed_keys and keyboard.Key.shift_r in pressed_keys:
        print(f"✅ Both shifts pressed! Keys: {pressed_keys}")
        print(f"   Left shift: {keyboard.Key.shift_l in pressed_keys}")
        print(f"   Right shift: {keyboard.Key.shift_r in pressed_keys}")

def on_release(key):
    """Handle key release events."""
    print(f"🔴 Key released: {key}")
    print(f"   Before removal - Keys held: {pressed_keys}")
    
    # Remove the key
    pressed_keys.discard(key)
    
    print(f"   After removal - Keys held: {pressed_keys}")
    print(f"   Left shift still held: {keyboard.Key.shift_l in pressed_keys}")
    print(f"   Right shift still held: {keyboard.Key.shift_r in pressed_keys}")
    
    # Check if we should stop PTT
    if not (keyboard.Key.shift_l in pressed_keys and keyboard.Key.shift_r in pressed_keys):
        print("   ⏹️  PTT should STOP now!")
    else:
        print("   ▶️  PTT should continue...")

def main():
    print("="*60)
    print("SHIFT KEY RELEASE TEST")
    print("="*60)
    print("\nPress Left Shift + Right Shift together")
    print("Then release ONE shift key and observe the output")
    print("Press Ctrl+C to exit\n")
    
    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\n\nExiting...")

if __name__ == "__main__":
    main()