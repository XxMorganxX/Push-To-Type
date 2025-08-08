import threading
import time
from typing import Callable, Optional, Set

from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventTapIsEnabled,
    CGEventSourceKeyState,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGAnnotatedSessionEventTap,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
    CGEventGetIntegerValueField,
    kCGKeyboardEventKeycode,
    kCGEventSourceStateCombinedSessionState,
)

# macOS keycodes for modifier keys we care about
KEYCODE_LEFT_SHIFT = 56
KEYCODE_RIGHT_SHIFT = 60


class EventTapPTTListener:
    """Global keyboard listener using a Quartz CGEvent tap with auto re-enable.

    Tracks pressed modifier keys and triggers callbacks on PTT press/release.
    Supports a left+right shift modifier-only bind reliably.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        require_left_right_shift: bool = True,
    ) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.require_left_right_shift = require_left_right_shift

        self._pressed: Set[str] = set()
        self._tap = None
        self._runloop_source = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._active = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_event_time = time.time()

    def _matches_ptt(self) -> bool:
        if self.require_left_right_shift:
            return self._pressed == {"shift_l", "shift_r"}
        return False

    def _handle_press(self):
        if not self._active and self._matches_ptt():
            self._active = True
            try:
                self.on_press()
            except Exception:
                pass

    def _handle_release(self):
        if self._active and not self._matches_ptt():
            self._active = False
            try:
                self.on_release()
            except Exception:
                pass

    def _event_callback(self, proxy, type_, event, refcon):
        # Update last event time
        self._last_event_time = time.time()
        
        # Re-enable tap if disabled by timeout
        if self._tap and not CGEventTapIsEnabled(self._tap):
            CGEventTapEnable(self._tap, True)
        try:
            if type_ in (kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged):
                # Derive current physical modifier state from system, avoids missed toggles
                left = CGEventSourceKeyState(kCGEventSourceStateCombinedSessionState, KEYCODE_LEFT_SHIFT)
                right = CGEventSourceKeyState(kCGEventSourceStateCombinedSessionState, KEYCODE_RIGHT_SHIFT)
                if left:
                    self._pressed.add("shift_l")
                else:
                    self._pressed.discard("shift_l")
                if right:
                    self._pressed.add("shift_r")
                else:
                    self._pressed.discard("shift_r")

                # Evaluate state transitions
                self._handle_press()
                self._handle_release()
        except Exception:
            pass
        return event

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._last_event_time = time.time()

        def _run():
            from Quartz import CFRunLoopSourceInvalidate, CFRunLoopRunInMode  # lazy import
            # Create event tap
            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                (1 << kCGEventKeyDown)
                | (1 << kCGEventKeyUp)
                | (1 << kCGEventFlagsChanged),
                self._event_callback,
                None,
            )
            if not self._tap:
                # Fallback to annotated session tap
                self._tap = CGEventTapCreate(
                    kCGAnnotatedSessionEventTap,
                    kCGHeadInsertEventTap,
                    kCGEventTapOptionListenOnly,
                    (1 << kCGEventKeyDown)
                    | (1 << kCGEventKeyUp)
                    | (1 << kCGEventFlagsChanged),
                    self._event_callback,
                    None,
                )
            if not self._tap:
                # Cannot create tap; give up
                return

            self._runloop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(loop, self._runloop_source, 0)
            CGEventTapEnable(self._tap, True)

            # Run loop with timeout to allow periodic checks
            while not self._stop.is_set():
                try:
                    # Run for short intervals to allow checking stop condition
                    CFRunLoopRunInMode(0, 0.5, False)  # Run for 500ms max
                    
                    # Re-enable tap periodically if it got disabled
                    if self._tap and not CGEventTapIsEnabled(self._tap):
                        CGEventTapEnable(self._tap, True)
                        print("🔄 Re-enabled event tap")
                except Exception as e:
                    print(f"⚠️ RunLoop error: {e}")
                    time.sleep(0.05)

            # Cleanup
            try:
                if self._runloop_source is not None:
                    CFRunLoopSourceInvalidate = CFRunLoopSourceInvalidate  # just to satisfy linters
            except Exception:
                pass

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        
        # Start monitor thread
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(target=self._monitor_tap, daemon=True)
            self._monitor_thread.start()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _monitor_tap(self):
        """Monitor thread that ensures the event tap stays enabled."""
        while not self._stop.is_set():
            time.sleep(2.0)  # Check every 2 seconds
            try:
                if self._tap:
                    # Check if tap is disabled
                    if not CGEventTapIsEnabled(self._tap):
                        CGEventTapEnable(self._tap, True)
                        print("✅ Monitor: Re-enabled event tap")
                    
                    # Also check for stale events (no events in 30+ seconds might indicate issues)
                    time_since_last = time.time() - self._last_event_time
                    if time_since_last > 30:
                        # Force re-enable as precaution
                        CGEventTapEnable(self._tap, False)
                        time.sleep(0.01)
                        CGEventTapEnable(self._tap, True)
                        self._last_event_time = time.time()
                        print(f"🔄 Monitor: Refreshed event tap (no events for {time_since_last:.1f}s)")
            except Exception as e:
                print(f"⚠️ Monitor error: {e}")

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._tap:
                CGEventTapEnable(self._tap, False)
        except Exception:
            pass
        # Try to stop runloop
        try:
            CFRunLoopStop(CFRunLoopGetCurrent())
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        self._thread = None
        self._monitor_thread = None
        self._tap = None
        self._runloop_source = None


