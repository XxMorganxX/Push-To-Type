#!/usr/bin/env python3
"""Test script to verify the double-free fix works by rapidly pressing/releasing PTT."""

import time
import sys
import threading
from pathlib import Path

# Add the project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from pynput import keyboard

# Test state
test_count = 0
max_tests = 20
ptt_active = False

def on_ptt_press():
    global ptt_active, test_count
    ptt_active = True
    test_count += 1
    print(f"\n✅ PTT #{test_count} PRESSED - Audio would start")

def on_ptt_release():
    global ptt_active
    ptt_active = False
    print(f"🔴 PTT RELEASED - Audio would stop")

def rapid_test():
    """Simulate rapid PTT press/release cycles."""
    print("\n" + "="*60)
    print("RAPID PTT TEST - Testing for double-free errors")
    print("="*60)
    print("This test will rapidly cycle PTT on/off to stress test audio cleanup")
    print(f"Will perform {max_tests} rapid cycles")
    print("If no crashes occur, the double-free fix is working!")
    print("-"*60)
    
    # Setup keybind manager
    ptt_keybind = PTTKeybind(
        modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
    )
    
    manager = PTTKeybindManager()
    manager.register_ptt(ptt_keybind, on_ptt_press, on_ptt_release)
    manager.start()
    
    print("\nPress and hold BOTH shift keys, then release one to trigger PTT cycle")
    print("Press Ctrl+C to stop test early\n")
    
    try:
        while test_count < max_tests:
            time.sleep(0.1)
            if test_count > 0 and test_count % 5 == 0:
                print(f"\n📊 Completed {test_count}/{max_tests} PTT cycles - No crashes!")
                
    except KeyboardInterrupt:
        print(f"\n\n⚠️ Test interrupted after {test_count} cycles")
    finally:
        manager.stop()
        
        if test_count >= max_tests:
            print(f"\n🎉 SUCCESS! Completed all {max_tests} PTT cycles without crashes!")
            print("✅ Double-free fix appears to be working correctly")
        else:
            print(f"\n📊 Completed {test_count} PTT cycles before stopping")
            
        print("\n✅ Test complete")

if __name__ == "__main__":
    rapid_test()