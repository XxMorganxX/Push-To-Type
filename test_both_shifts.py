#!/usr/bin/env python3
"""Test that both left and right shift releases work properly."""

import time
import sys
from core.ptt_keybind_manager import PTTKeybind, PTTKeybindManager
from pynput import keyboard

ptt_active = False
test_results = []

def on_ptt_press():
    global ptt_active
    ptt_active = True
    print("\n✅ PTT PRESSED - Recording started")
    print("   Both shifts are pressed")
    print("   Release EITHER shift to stop")

def on_ptt_release():
    global ptt_active
    ptt_active = False
    print("🔴 PTT RELEASED - Recording stopped")
    print("   One or both shifts were released\n")

def test_sequence():
    """Run through test sequence."""
    print("\nTEST SEQUENCE:")
    print("-" * 40)
    print("1. Press LEFT SHIFT")
    print("2. Press RIGHT SHIFT (both held)")
    print("   → Verify PTT starts")
    print("3. Release RIGHT SHIFT")
    print("   → Verify PTT stops immediately")
    print("4. Press RIGHT SHIFT again")
    print("   → Verify PTT starts again")
    print("5. Release LEFT SHIFT")
    print("   → Verify PTT stops immediately")
    print("-" * 40)

def main():
    print("="*60)
    print("BOTH SHIFT KEYS RELEASE TEST")
    print("="*60)
    
    # Create PTT keybind for left+right shift
    ptt_keybind = PTTKeybind(
        modifiers={keyboard.Key.shift_l, keyboard.Key.shift_r}
    )
    
    # Setup keybind manager
    manager = PTTKeybindManager()
    manager.register_ptt(ptt_keybind, on_ptt_press, on_ptt_release)
    manager.start()
    
    test_sequence()
    
    try:
        print("\nReady for testing...")
        print("Press Ctrl+C to exit\n")
        
        start_time = time.time()
        while True:
            time.sleep(0.1)
            # Show status periodically
            if int(time.time() - start_time) % 5 == 0:
                status = "🔴 IDLE" if not ptt_active else "🟢 RECORDING"
                print(f"Status: {status}", end="\r", flush=True)
                
    except KeyboardInterrupt:
        print("\n\nStopping...")
        manager.stop()
        print("Test complete!")

if __name__ == "__main__":
    main()