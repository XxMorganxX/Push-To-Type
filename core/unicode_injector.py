import time
import threading
from queue import Queue, Empty
from typing import Optional, Callable, Tuple, Literal
import subprocess
from Quartz.CoreGraphics import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSourceCreate,
    CGEventKeyboardSetUnicodeString,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGEventSourceStateHIDSystemState,
    kCGHIDEventTap,
)


class UnicodeInjector:
    """
    Handles direct Unicode character injection using Quartz Core Graphics.
    Bypasses modifier keys and provides character-by-character typing with interruption checks.
    """
    
    def __init__(
        self,
        typing_delay: float = 0.005,
        mode: Literal["keystroke", "paste"] = "paste",
        preserve_clipboard: bool = True,
    ):
        """
        Initialize the Unicode injector.
        
        Args:
            typing_delay: Delay between characters in seconds (default 5ms)
        """
        self.typing_delay = typing_delay
        self.mode: Literal["keystroke", "paste"] = mode
        self.preserve_clipboard = bool(preserve_clipboard)
        self.stop_typing = threading.Event()
        self.typing_thread: Optional[threading.Thread] = None
        self.event_source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        # Queue-based typing to avoid overlapping threads that can drop first characters
        # Items are tuples: (generation, text, interrupt_check)
        self._text_queue: "Queue[Tuple[int, str, Optional[Callable[[], bool]]]]" = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop = threading.Event()
        # Generation invalidation for immediate shutdown and race-proof dropping of in-flight work
        self._generation = 0
        # Gate to allow permanent disable during app shutdown
        self._accept_new_work = True
        # Lock protecting generation and gate
        self._lock = threading.Lock()
        # Track when last character was injected (for drain timing)
        self._last_inject_time = 0.0
        # Track if currently mid-injection to help with idle detection
        self._injecting = threading.Event()
        
    def inject_text(self, text: str, interrupt_check: Optional[Callable[[], bool]] = None):
        """
        Queue text for injection, typed by a single background worker to maintain order.
        """
        if not text:
            return
        self.stop_typing.clear()
        # Respect gate: drop any new work when disabled
        with self._lock:
            if not self._accept_new_work:
                return
            gen = self._generation
        # Enqueue with generation and per-item interrupt check
        self._text_queue.put((gen, text, interrupt_check))
        if not self._worker_thread or not self._worker_thread.is_alive():
            self._start_worker()

    def _start_worker(self):
        self._worker_stop.clear()

        def _worker():
            # Slightly longer initial delay to help avoid first-character clipping
            time.sleep(0.02)
            while not self._worker_stop.is_set():
                # Check gate before even trying to get work
                with self._lock:
                    if not self._accept_new_work:
                        break
                try:
                    item = self._text_queue.get(timeout=0.1)
                except Empty:
                    continue
                # Backward-compat: allow plain strings if ever enqueued elsewhere
                if isinstance(item, tuple) and len(item) == 3:
                    item_gen, pending, interrupt_check = item
                else:
                    item_gen, pending, interrupt_check = self._generation, item, None
                # Drop stale work immediately if generation changed or gate closed
                with self._lock:
                    current_gen = self._generation
                    gate_open = self._accept_new_work
                if item_gen != current_gen or not gate_open:
                    self._text_queue.task_done()
                    continue
                # Type this chunk with per-char abort checks
                if self.mode == "paste":
                    # Paste the whole chunk in one shot (dramatically fewer HID events)
                    self._paste_text(pending, item_gen=item_gen)
                else:
                    for char in pending:
                        # Re-evaluate stop, generation, and gate on every character
                        with self._lock:
                            current_gen = self._generation
                            gate_open = self._accept_new_work
                        if (self.stop_typing.is_set() or self._worker_stop.is_set() or
                            item_gen != current_gen or not gate_open):
                            break
                        if interrupt_check and interrupt_check():
                            break
                        self._inject_character(char)
                        time.sleep(self.typing_delay)
                self._text_queue.task_done()

        self._worker_thread = threading.Thread(target=_worker, daemon=True)
        self._worker_thread.start()
    
    def _inject_character(self, char: str):
        """
        Inject a single Unicode character using Quartz events.
        
        Args:
            char: Single character to inject
        """
        if not char:
            return
        
        # Check if we should still be injecting (shutdown guard)
        with self._lock:
            if not self._accept_new_work:
                return
        
        self._injecting.set()
        try:
            # Create keyboard event with Unicode string
            event = CGEventCreateKeyboardEvent(self.event_source, 0, True)
            
            # Set the Unicode string using the proper API
            # The function takes: event, string length, and the string
            CGEventKeyboardSetUnicodeString(event, len(char), char)
            
            # Post the event
            CGEventPost(kCGHIDEventTap, event)
            
            # Create and post key up event
            event_up = CGEventCreateKeyboardEvent(self.event_source, 0, False)
            CGEventKeyboardSetUnicodeString(event_up, len(char), char)
            CGEventPost(kCGHIDEventTap, event_up)
            
            # Track last injection time for drain timing
            self._last_inject_time = time.time()
        finally:
            self._injecting.clear()

    def _paste_text(self, text: str, item_gen: int):
        """
        Paste text using clipboard + Cmd+V to minimize queued HID keystrokes.
        This reduces shutdown 'flush' dramatically vs per-character injection.
        """
        if not text:
            return

        # Check gate/generation before doing any work
        with self._lock:
            if not self._accept_new_work or item_gen != self._generation:
                return

        self._injecting.set()
        old_clip = None
        try:
            if self.preserve_clipboard:
                try:
                    old_clip = subprocess.run(
                        ["/usr/bin/pbpaste"],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    ).stdout
                except Exception:
                    old_clip = None

            # Set clipboard
            subprocess.run(
                ["/usr/bin/pbcopy"],
                input=text.encode("utf-8", errors="replace"),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Post Cmd+V (keycode for 'v' is 9 on macOS)
            V_KEYCODE = 9
            down = CGEventCreateKeyboardEvent(self.event_source, V_KEYCODE, True)
            CGEventSetFlags(down, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, down)

            up = CGEventCreateKeyboardEvent(self.event_source, V_KEYCODE, False)
            CGEventSetFlags(up, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, up)

            self._last_inject_time = time.time()
        finally:
            # Best-effort restore clipboard
            if self.preserve_clipboard and old_clip is not None:
                try:
                    subprocess.run(
                        ["/usr/bin/pbcopy"],
                        input=old_clip,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            self._injecting.clear()
    
    def stop(self, invalidate_generation: bool = True):
        """Stop any ongoing typing operation and optionally invalidate in-flight work."""
        self.stop_typing.set()
        self._worker_stop.set()
        # Invalidate any currently queued or in-flight items
        if invalidate_generation:
            with self._lock:
                self._generation += 1
        # Drain queue quickly
        try:
            while True:
                self._text_queue.get_nowait()
                self._text_queue.task_done()
        except Empty:
            pass
        if self._worker_thread and self._worker_thread.is_alive():
            # Give the worker more time to exit cleanly; short timeouts can leave
            # already-dequeued characters still being posted during shutdown.
            self._worker_thread.join(timeout=2.0)
        self._worker_thread = None

    def disable(self):
        """Permanently disable output until re-enabled; drop any queued/in-flight text immediately."""
        with self._lock:
            self._accept_new_work = False
            self._generation += 1
        # Stop without bumping generation again
        self.stop(invalidate_generation=False)

    def enable(self):
        """Re-enable accepting new work (does not start typing by itself)."""
        with self._lock:
            self._accept_new_work = True

    def flush_and_clear(self):
        """
        Emergency flush: immediately stop all injection and clear any pending work.
        This prevents spurious character output on shutdown.
        """
        # Close the gate immediately to prevent any new injections
        with self._lock:
            self._accept_new_work = False
            self._generation += 1
        
        # Signal all stop conditions
        self.stop_typing.set()
        self._worker_stop.set()
        
        # Drain the queue completely
        try:
            while True:
                self._text_queue.get_nowait()
                self._text_queue.task_done()
        except Empty:
            pass
        
        # Wait briefly for any in-flight CGEvent to finish
        # (CGEventPost is async, so give system time to process)
        wait_start = time.time()
        while self._injecting.is_set() and (time.time() - wait_start) < 0.1:
            time.sleep(0.005)
        
        # Wait for worker thread to exit
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        self._worker_thread = None
        
        # Small delay to let macOS HID system drain any already-posted events
        # This is critical: events posted to kCGHIDEventTap are in a system buffer
        time_since_last = time.time() - self._last_inject_time
        # Use a slightly longer drain window; on Ctrl+C users tend to notice even
        # small bursts of buffered characters.
        drain_s = 0.25
        if time_since_last < drain_s:
            time.sleep(drain_s - time_since_last)

    def wait_idle(self, timeout: float = 1.0) -> bool:
        """
        Wait for the injector to become idle (no pending work).
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if idle, False if timeout expired
        """
        start = time.time()
        while (time.time() - start) < timeout:
            # Check if worker is dead or queue is empty
            worker_idle = not self._worker_thread or not self._worker_thread.is_alive()
            queue_empty = self._text_queue.empty()
            not_injecting = not self._injecting.is_set()
            
            if (worker_idle or queue_empty) and not_injecting:
                # Additional small wait for CGEvent system buffer
                time_since_last = time.time() - self._last_inject_time
                if time_since_last >= 0.05:
                    return True
                time.sleep(0.05 - time_since_last)
                return True
            
            time.sleep(0.01)
        return False
    
    def inject_backspace(self, count: int = 1):
        """
        Inject backspace key presses.
        
        Args:
            count: Number of backspaces to send
        """
        for _ in range(count):
            # Check gate before injecting
            with self._lock:
                if not self._accept_new_work:
                    return
            
            # Keycode 51 is Delete/Backspace on macOS
            event_down = CGEventCreateKeyboardEvent(self.event_source, 51, True)
            CGEventPost(kCGHIDEventTap, event_down)
            
            event_up = CGEventCreateKeyboardEvent(self.event_source, 51, False)
            CGEventPost(kCGHIDEventTap, event_up)
            
            self._last_inject_time = time.time()
            time.sleep(0.01)  # Small delay between backspaces
    
    def is_typing(self) -> bool:
        """Check if currently typing."""
        return bool(self._worker_thread and self._worker_thread.is_alive())
    
    def wait_for_completion(self, timeout: Optional[float] = None):
        """
        Wait for current typing operation to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        if self.typing_thread and self.typing_thread.is_alive():
            self.typing_thread.join(timeout=timeout)