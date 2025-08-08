#!/usr/bin/env python3
"""
Test the integrated PTT keybind implementation.
"""

import time
import sys
from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from pynput import keyboard

def test_integration():
    print("=" * 60)
    print("🧪 TESTING INTEGRATED PTT IMPLEMENTATION")
    print("=" * 60)
    print("\nThis test verifies the new cleaner implementation works correctly.")
    print("\n📋 Instructions:")
    print("1. Press and hold BOTH left AND right shift keys")
    print("2. You should see 'PTT ACTIVATED' message")
    print("3. Release either shift key")
    print("4. You should see 'PTT DEACTIVATED' message")
    print("5. Press Ctrl+C to exit\n")
    print("=" * 60)
    
    # Track press/release events
    press_count = 0
    release_count = 0
    
    def on_press():
        nonlocal press_count
        press_count += 1
        print(f"\n✅ PTT ACTIVATED (#{press_count}) - Both shift keys detected!")
        
    def on_release():
        nonlocal release_count
        release_count += 1
        print(f"🔴 PTT DEACTIVATED (#{release_count}) - Shift key(s) released")
    
    # Create and configure the manager
    manager = PTTKeybindManager()
    
    # Create keybind for left+right shift
    keybind = PTTKeybind(
        modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
    )
    
    # Register the keybind
    manager.register_ptt(keybind, on_press, on_release)
    
    # Start listening
    print("\n🚀 Starting listener...")
    manager.start()
    print("✅ Listener active - Ready for testing\n")
    
    try:
        # Keep running until interrupted
        while True:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\n📊 Test Results:")
        print(f"   Press events: {press_count}")
        print(f"   Release events: {release_count}")
        
        if press_count > 0 and release_count > 0:
            print("\n✅ SUCCESS: The integrated implementation is working correctly!")
        elif press_count == 0:
            print("\n⚠️  No press events detected")
        elif release_count == 0:
            print("\n⚠️  No release events detected")
            
    finally:
        print("\n🔄 Cleaning up...")
        manager.stop()
        print("✅ Test complete")

if __name__ == "__main__":
    test_integration()