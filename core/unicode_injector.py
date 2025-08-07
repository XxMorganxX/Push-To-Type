import time
import threading
from queue import Queue, Empty
from typing import Optional, Callable
from Quartz.CoreGraphics import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSourceCreate,
    CGEventKeyboardSetUnicodeString,
    kCGEventSourceStateHIDSystemState,
    kCGHIDEventTap,
)


class UnicodeInjector:
    """
    Handles direct Unicode character injection using Quartz Core Graphics.
    Bypasses modifier keys and provides character-by-character typing with interruption checks.
    """
    
    def __init__(self, typing_delay: float = 0.005):
        """
        Initialize the Unicode injector.
        
        Args:
            typing_delay: Delay between characters in seconds (default 5ms)
        """
        self.typing_delay = typing_delay
        self.stop_typing = threading.Event()
        self.typing_thread: Optional[threading.Thread] = None
        self.event_source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        # Queue-based typing to avoid overlapping threads that can drop first characters
        self._text_queue: "Queue[str]" = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop = threading.Event()
        
    def inject_text(self, text: str, interrupt_check: Optional[Callable[[], bool]] = None):
        """
        Queue text for injection, typed by a single background worker to maintain order.
        """
        if not text:
            return
        self.stop_typing.clear()
        # Wrap text with an interrupt-check hook by placing a sentinel in the queue if needed
        # We'll store a tuple-like protocol as a string is sufficient; keep interrupt_check in instance
        self._current_interrupt_check = interrupt_check
        self._text_queue.put(text)
        if not self._worker_thread or not self._worker_thread.is_alive():
            self._start_worker()

    def _start_worker(self):
        self._worker_stop.clear()

        def _worker():
            # Slightly longer initial delay to help avoid first-character clipping
            time.sleep(0.02)
            while not self._worker_stop.is_set():
                try:
                    pending = self._text_queue.get(timeout=0.1)
                except Empty:
                    continue
                # Type this chunk
                for char in pending:
                    if self.stop_typing.is_set() or self._worker_stop.is_set():
                        break
                    if getattr(self, "_current_interrupt_check", None) and self._current_interrupt_check():
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
    
    def stop(self):
        """Stop any ongoing typing operation."""
        self.stop_typing.set()
        self._worker_stop.set()
        # Drain queue
        try:
            while True:
                self._text_queue.get_nowait()
                self._text_queue.task_done()
        except Empty:
            pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
    
    def inject_backspace(self, count: int = 1):
        """
        Inject backspace key presses.
        
        Args:
            count: Number of backspaces to send
        """
        for _ in range(count):
            # Keycode 51 is Delete/Backspace on macOS
            event_down = CGEventCreateKeyboardEvent(self.event_source, 51, True)
            CGEventPost(kCGHIDEventTap, event_down)
            
            event_up = CGEventCreateKeyboardEvent(self.event_source, 51, False)
            CGEventPost(kCGHIDEventTap, event_up)
            
            time.sleep(0.01)  # Small delay between backspaces
    
    def is_typing(self) -> bool:
        """Check if currently typing."""
        return self.typing_thread and self.typing_thread.is_alive()
    
    def wait_for_completion(self, timeout: Optional[float] = None):
        """
        Wait for current typing operation to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        if self.typing_thread and self.typing_thread.is_alive():
            self.typing_thread.join(timeout=timeout)