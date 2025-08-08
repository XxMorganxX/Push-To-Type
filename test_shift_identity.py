#!/usr/bin/env python3
"""Test script to check shift key identity tracking."""

from pynput import keyboard

def on_press(key):
    """Handle key press events."""
    print(f"🟢 Pressed: {key}")
    print(f"   Type: {type(key)}")
    print(f"   Is shift_l? {key == keyboard.Key.shift_l}")
    print(f"   Is shift_r? {key == keyboard.Key.shift_r}")
    print(f"   Is generic shift? {key == keyboard.Key.shift}")
    print()

def on_release(key):
    """Handle key release events."""
    print(f"🔴 Released: {key}")
    print(f"   Type: {type(key)}")
    print(f"   Is shift_l? {key == keyboard.Key.shift_l}")
    print(f"   Is shift_r? {key == keyboard.Key.shift_r}")
    print(f"   Is generic shift? {key == keyboard.Key.shift}")
    print()
    
    if key == keyboard.Key.esc:
        return False

def main():
    print("="*60)
    print("SHIFT KEY IDENTITY TEST")
    print("="*60)
    print("\nPress Left Shift, then Right Shift")
    print("Observe if they're properly distinguished")
    print("Press ESC to exit\n")
    
    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:
        listener.join()

if __name__ == "__main__":
    main()