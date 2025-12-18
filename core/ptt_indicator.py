"""
Minimal PTT indicator overlay using PyObjC.
Shows a small colored dot on screen when PTT is active.
"""

import threading
from typing import Optional, Tuple

import objc
from Foundation import NSMakeRect, NSRunLoop, NSDefaultRunLoopMode, NSDate
from AppKit import (
    NSApplication,
    NSWindow,
    NSView,
    NSColor,
    NSBezierPath,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSScreen,
    NSApp,
)


class IndicatorView(NSView):
    """Custom view that draws a colored circle."""
    
    def initWithFrame_color_(self, frame, color):
        self = objc.super(IndicatorView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._color = color
        return self
    
    def drawRect_(self, rect):
        # Draw filled circle
        self._color.setFill()
        path = NSBezierPath.bezierPathWithOvalInRect_(self.bounds())
        path.fill()
        
        # Draw subtle border for visibility
        NSColor.colorWithWhite_alpha_(0.0, 0.3).setStroke()
        path.setLineWidth_(1.5)
        path.stroke()
    
    def setColor_(self, color):
        self._color = color
        self.setNeedsDisplay_(True)
    
    def isOpaque(self):
        return False


class PTTIndicator:
    """
    Floating indicator dot that shows PTT state.
    IMPORTANT: Cocoa UI must be created and pumped on the main thread.
    This class is thread-safe for state changes (press/release callbacks) and
    expects the app to call `pump()` periodically from the main thread.
    
    States:
    - ready: Green - app is running and ready (idle)
    - active: Red - currently recording (PTT pressed)
    - processing: Yellow - processing between turns (waiting for final transcription)
    """
    
    def __init__(
        self,
        size: int = 20,
        position: Tuple[int, int] = (20, 20),  # From top-right corner
        ready_color: Tuple[float, float, float, float] = (0.2, 0.8, 0.2, 0.9),  # Green
        active_color: Tuple[float, float, float, float] = (1.0, 0.3, 0.3, 0.9),  # Red
        processing_color: Tuple[float, float, float, float] = (1.0, 0.8, 0.0, 0.9),  # Yellow
        idle_color: Optional[Tuple[float, float, float, float]] = None,  # For backwards compat
    ):
        """
        Initialize the PTT indicator.
        
        Args:
            size: Diameter of the indicator dot in pixels
            position: (x, y) offset from top-right corner of screen
            ready_color: RGBA tuple for ready state (0.0-1.0) - green
            active_color: RGBA tuple for active/recording state (0.0-1.0) - red
            processing_color: RGBA tuple for processing state (0.0-1.0) - yellow
            idle_color: RGBA tuple for idle state, or None (deprecated, use ready_color)
        """
        self.size = size
        self.position = position
        self.ready_color = ready_color if idle_color is None else idle_color
        self.active_color = active_color
        self.processing_color = processing_color
        
        self._window: Optional[NSWindow] = None
        self._view: Optional[IndicatorView] = None
        self._current_state = "ready"  # ready, active, processing
        self._lock = threading.Lock()
        self._initialized = False
        # Desired state set from any thread; applied in `pump()` on main thread
        self._desired_state: Optional[str] = "ready"

    def initialize(self):
        """
        Initialize the Cocoa window. Must be called from the main thread.
        Safe to call multiple times.
        """
        if self._initialized:
            return
        # Ensure NSApplication exists (needed for window to work)
        if NSApp() is None:
            NSApplication.sharedApplication()
        self._create_window()
    
    def _create_window(self):
        """Create the indicator window."""
        try:
            # Get screen dimensions
            screen = NSScreen.mainScreen()
            if not screen:
                print("⚠️ No main screen found for indicator")
                return
            screen_frame = screen.frame()
            
            # Calculate position (top-right corner offset)
            x = screen_frame.size.width - self.position[0] - self.size
            y = screen_frame.size.height - self.position[1] - self.size
            
            # Create window
            frame = NSMakeRect(x, y, self.size, self.size)
            self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            
            # Configure window
            self._window.setLevel_(NSFloatingWindowLevel + 100)  # Very high level
            self._window.setOpaque_(False)
            self._window.setBackgroundColor_(NSColor.clearColor())
            self._window.setIgnoresMouseEvents_(True)  # Click-through
            self._window.setHasShadow_(False)
            
            # Make it appear on all spaces
            self._window.setCollectionBehavior_(
                (1 << 0) |  # NSWindowCollectionBehaviorCanJoinAllSpaces
                (1 << 3) |  # NSWindowCollectionBehaviorStationary  
                (1 << 9)    # NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            
            # Create indicator view with initial ready color (green)
            initial_color = NSColor.colorWithRed_green_blue_alpha_(*self.ready_color)
            
            view_frame = NSMakeRect(0, 0, self.size, self.size)
            self._view = IndicatorView.alloc().initWithFrame_color_(view_frame, initial_color)
            self._window.setContentView_(self._view)
            
            self._initialized = True
            
            # Always show window (starts in ready state)
            self._window.orderFrontRegardless()
                
        except Exception as e:
            print(f"⚠️ Failed to create indicator window: {e}")
    
    def _cleanup_window(self):
        """Clean up the window."""
        try:
            if self._window:
                self._window.orderOut_(None)
                self._window.close()
                self._window = None
            self._view = None
            self._initialized = False
        except Exception:
            pass
    
    def show_ready(self):
        """Show the indicator in ready state (green - app running, waiting for PTT)."""
        with self._lock:
            self._desired_state = "ready"
    
    def show_active(self):
        """Show the indicator in active state (red - recording)."""
        with self._lock:
            self._desired_state = "active"
    
    def show_processing(self):
        """Show the indicator in processing state (yellow - waiting for final transcription)."""
        with self._lock:
            self._desired_state = "processing"
    
    def show_idle(self):
        """Alias for show_ready() for backwards compatibility."""
        self.show_ready()
    
    def hide(self):
        """Completely hide the indicator (not recommended, use show_ready instead)."""
        with self._lock:
            self._desired_state = None
        # Apply immediately if we're already on main thread and initialized
        if self._window:
            try:
                self._window.orderOut_(None)
            except Exception:
                pass

    def pump(self, max_step_s: float = 0.01):
        """
        Pump the Cocoa run loop and apply any pending indicator state.
        Must be called periodically from the main thread.
        """
        # Ensure initialized on the main thread
        if not self._initialized:
            self.initialize()

        # Apply desired state (set by other threads)
        with self._lock:
            desired = self._desired_state
            # Don't clear _desired_state - keep it so we can check current state

        if desired is not None and desired != self._current_state:
            self._apply_state(desired)

        # Pump the run loop briefly so the window can render/update
        try:
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode,
                NSDate.dateWithTimeIntervalSinceNow_(max_step_s),
            )
        except Exception:
            pass

    def _apply_state(self, state: str):
        """Apply a state change to the indicator."""
        if not (self._window and self._view):
            return
        
        try:
            if state == "active":
                # Red - recording
                color = NSColor.colorWithRed_green_blue_alpha_(*self.active_color)
                self._view.setColor_(color)
                self._window.orderFrontRegardless()
            elif state == "processing":
                # Yellow - processing between turns
                color = NSColor.colorWithRed_green_blue_alpha_(*self.processing_color)
                self._view.setColor_(color)
                self._window.orderFrontRegardless()
            elif state == "ready":
                # Green - ready/idle
                color = NSColor.colorWithRed_green_blue_alpha_(*self.ready_color)
                self._view.setColor_(color)
                self._window.orderFrontRegardless()
            elif state is None:
                # Hidden
                self._window.orderOut_(None)
            
            self._current_state = state
        except Exception:
            pass
    
    def cleanup(self):
        """Clean up resources."""
        self._cleanup_window()


def create_indicator(config: Optional[dict] = None) -> PTTIndicator:
    """
    Factory function to create a PTT indicator from config.
    
    Args:
        config: Optional dict with keys:
            - size: int (default 20)
            - position_x: int (default 20) 
            - position_y: int (default 20)
            - ready_color: [r, g, b, a] (default green) - app is running/idle
            - active_color: [r, g, b, a] (default red) - recording
            - processing_color: [r, g, b, a] (default yellow) - processing between turns
            - idle_color: [r, g, b, a] or null (deprecated, use ready_color)
            - enabled: bool (default True)
    
    Returns:
        PTTIndicator instance
    """
    if config is None:
        config = {}
    
    size = config.get("size", 20)
    pos_x = config.get("position_x", 30)
    pos_y = config.get("position_y", 30)
    
    ready = config.get("ready_color", [0.2, 0.8, 0.2, 0.9])  # Green
    active = config.get("active_color", [1.0, 0.2, 0.2, 0.95])  # Red
    processing = config.get("processing_color", [1.0, 0.8, 0.0, 0.9])  # Yellow
    idle = config.get("idle_color", None)  # Backwards compat
    
    return PTTIndicator(
        size=size,
        position=(pos_x, pos_y),
        ready_color=tuple(ready),
        active_color=tuple(active),
        processing_color=tuple(processing),
        idle_color=tuple(idle) if idle else None,
    )
