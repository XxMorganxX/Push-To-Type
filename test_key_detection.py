#!/usr/bin/env python3
"""
Test script to verify key detection is working correctly.
"""

import time
from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from core.event_tap_listener import EventTapPTTListener
from pynput import keyboard
from Quartz import CGEventSourceKeyState, kCGEventSourceStateCombinedSessionState

# Track test results
press_count = 0
release_count = 0

def on_ptt_press():
    global press_count
    press_count += 1
    print(f"\n✅ PTT PRESS #{press_count} detected!")
    print("   Both shift keys are being held down correctly")

def on_ptt_release():
    global release_count
    release_count += 1
    print(f"🔴 PTT RELEASE #{release_count} detected!")
    print("   One or both shift keys were released")

def test_key_detection():
    print("=" * 60)
    print("🧪 TESTING KEY DETECTION")
    print("=" * 60)
    print("This test verifies that:")
    print("1. PTT only activates when BOTH left AND right shift are pressed")
    print("2. PTT deactivates when either shift key is released")
    print("\n🎯 INSTRUCTIONS:")
    print("- Press BOTH shift keys simultaneously to test activation")
    print("- Release either shift key to test deactivation")
    print("- Try pressing only ONE shift key (should NOT activate)")
    print("- Press Ctrl+C when done testing")
    print("=" * 60)

    # Create the PTT keybind for left+right shift
    ptt_keybind = PTTKeybind(
        modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
    )
    print(f"🔧 PTT Keybind configured with modifiers: {ptt_keybind.modifiers}")
    
    # Start both listeners for comprehensive testing
    print("\n🚀 Starting listeners...")
    
    # PTTKeybindManager test
    kbm = PTTKeybindManager()
    kbm.register_ptt(ptt_keybind, on_ptt_press, on_ptt_release)
    kbm.start()
    print("✅ PTTKeybindManager started")
    
    # Quartz Event Tap test  
    quartz_listener = EventTapPTTListener(
        on_ptt_press, on_ptt_release, require_left_right_shift=True
    )
    quartz_listener.start()
    print("✅ Quartz EventTapPTTListener started")
    
    print("\n🔍 Monitoring key state...")
    print("Left Shift keycode: 56, Right Shift keycode: 60")
    
    try:
        last_left = False
        last_right = False
        
        while True:
            time.sleep(0.1)
            
            # Check current key states
            left = bool(CGEventSourceKeyState(kCGEventSourceStateCombinedSessionState, 56))
            right = bool(CGEventSourceKeyState(kCGEventSourceStateCombinedSessionState, 60))
            
            # Only print state changes to avoid spam
            if left != last_left or right != last_right:
                status = "🔴"
                if left and right:
                    status = "🟢"
                elif left or right:
                    status = "🟡"
                    
                print(f"\r{status} Left: {left}, Right: {right}", end="", flush=True)
                last_left = left
                last_right = right
                
    except KeyboardInterrupt:
        print(f"\n\n📊 TEST RESULTS:")
        print(f"   PTT Press events detected: {press_count}")
        print(f"   PTT Release events detected: {release_count}")
        
        if press_count > 0 and release_count > 0:
            print("✅ Key detection appears to be working correctly!")
        elif press_count == 0:
            print("⚠️  No PTT press events detected - check key listeners")
        else:
            print("⚠️  Incomplete test - try holding and releasing both shifts")
            
    finally:
        print("\n🔄 Cleaning up...")
        try:
            kbm.stop()
            print("✅ PTTKeybindManager stopped")
        except:
            pass
        try:
            quartz_listener.stop()  
            print("✅ Quartz listener stopped")
        except:
            pass
        print("✅ Test complete")

if __name__ == "__main__":
    test_key_detection()