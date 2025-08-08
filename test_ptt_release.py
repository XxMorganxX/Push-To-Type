#!/usr/bin/env python3
"""Test script to verify PTT shift key release is working properly."""

import time
import sys
from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from pynput import keyboard

def on_ptt_press():
    print("\n✅ PTT PRESSED - Recording started")
    print("   Release either shift key to stop")

def on_ptt_release():
    print("🔴 PTT RELEASED - Recording stopped\n")

def main():
    print("="*60)
    print("PTT SHIFT KEY RELEASE TEST")
    print("="*60)
    print("\n1. Press and hold BOTH shift keys (left + right)")
    print("2. Release EITHER shift key")
    print("3. Verify that PTT stops immediately upon release")
    print("\nPress Ctrl+C to exit\n")
    
    # Create PTT keybind for left+right shift
    ptt_keybind = PTTKeybind(
        modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
    )
    
    # Setup keybind manager
    manager = PTTKeybindManager()
    manager.register_ptt(ptt_keybind, on_ptt_press, on_ptt_release)
    manager.start()
    
    try:
        print("Ready - waiting for shift keys...")
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nStopping...")
        manager.stop()
        print("Test complete!")

if __name__ == "__main__":
    main()