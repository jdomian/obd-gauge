"""
OBD-Gauge Touch Handler - Gesture detection for HyperPixel 2.1 Round
Uses hyperpixel2r library with GPIO interrupt for instant touch response.

REQUIRES: dtoverlay=hyperpixel2r:disable-touch in /boot/config.txt
This allows Python to access the touch controller via I2C.
"""

import time
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional

# Touch constants
SWIPE_THRESHOLD = 50  # Minimum pixels for swipe
TAP_MAX_DURATION = 300  # Max ms for tap
LONG_PRESS_DURATION = 500  # Min ms for long press


class GestureType(Enum):
    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"


@dataclass
class TouchEvent:
    """Represents a touch event with position and timing."""
    x: int
    y: int
    timestamp: float


@dataclass
class Gesture:
    """Detected gesture with metadata."""
    type: GestureType
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: float


class TouchHandler:
    """
    Handles touch input from HyperPixel 2r display.
    Uses hyperpixel2r library with GPIO interrupt for minimal latency.
    """

    def __init__(self):
        self.touch = None
        self.callbacks: dict = {}
        self._initialized = False

        # Touch state
        self._touch_start: Optional[TouchEvent] = None
        self._current_x = 0
        self._current_y = 0

    def initialize(self) -> bool:
        """Initialize touch input using hyperpixel2r library."""
        try:
            from hyperpixel2r import Touch

            # Create touch handler - let library auto-detect settings
            self.touch = Touch()

            # Register our callback
            @self.touch.on_touch
            def handle_touch(touch_id, x, y, state):
                self._process_touch(x, y, state)

            print(f"  Touch: hyperpixel2r (GPIO interrupt)")
            self._initialized = True
            return True

        except ImportError:
            print("Warning: hyperpixel2r not installed. Touch disabled.")
            return False
        except Exception as e:
            print(f"Warning: Touch init failed: {e}")
            return False

    def _process_touch(self, x: int, y: int, state: bool):
        """Process touch event from hyperpixel2r callback."""
        # Always update current position for tracking drag
        self._current_x = x
        self._current_y = y

        if state:  # Touch down / drag
            # Only set start on FIRST touch (not during drag)
            if self._touch_start is None:
                self._touch_start = TouchEvent(
                    x=x,
                    y=y,
                    timestamp=time.time()
                )
        else:  # Touch up
            if self._touch_start:
                self._handle_gesture()
            self._touch_start = None

    def _handle_gesture(self):
        """Process completed touch into gesture."""
        if not self._touch_start:
            return

        start = self._touch_start
        end_x = self._current_x
        end_y = self._current_y
        duration_ms = (time.time() - start.timestamp) * 1000

        dx = end_x - start.x
        dy = end_y - start.y
        abs_dx = abs(dx)
        abs_dy = abs(dy)

        # Classify gesture
        gesture_type = None
        if abs_dx > SWIPE_THRESHOLD or abs_dy > SWIPE_THRESHOLD:
            if abs_dx > abs_dy:
                gesture_type = GestureType.SWIPE_LEFT if dx < 0 else GestureType.SWIPE_RIGHT
            else:
                gesture_type = GestureType.SWIPE_UP if dy < 0 else GestureType.SWIPE_DOWN
        elif duration_ms > LONG_PRESS_DURATION:
            gesture_type = GestureType.LONG_PRESS
        elif duration_ms < TAP_MAX_DURATION:
            gesture_type = GestureType.TAP

        if gesture_type and gesture_type in self.callbacks:
            gesture = Gesture(
                type=gesture_type,
                start_x=start.x,
                start_y=start.y,
                end_x=end_x,
                end_y=end_y,
                duration_ms=duration_ms
            )
            for callback in self.callbacks[gesture_type]:
                try:
                    callback(gesture)
                except Exception as e:
                    print(f"Callback error: {e}")

    def on_gesture(self, gesture_type: GestureType, callback: Callable[[Gesture], None]):
        """Register a callback for a gesture type."""
        if gesture_type not in self.callbacks:
            self.callbacks[gesture_type] = []
        self.callbacks[gesture_type].append(callback)

    def on_swipe_left(self, callback: Callable[[Gesture], None]):
        self.on_gesture(GestureType.SWIPE_LEFT, callback)

    def on_swipe_right(self, callback: Callable[[Gesture], None]):
        self.on_gesture(GestureType.SWIPE_RIGHT, callback)

    def on_tap(self, callback: Callable[[Gesture], None]):
        self.on_gesture(GestureType.TAP, callback)

    def on_long_press(self, callback: Callable[[Gesture], None]):
        self.on_gesture(GestureType.LONG_PRESS, callback)

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class MockTouchHandler(TouchHandler):
    """Mock touch handler for testing without hardware."""

    def initialize(self) -> bool:
        self._initialized = True
        print("Using mock touch handler")
        return True

    def simulate_gesture(self, gesture_type: GestureType):
        """Simulate a gesture for testing."""
        gesture = Gesture(
            type=gesture_type,
            start_x=240, start_y=240,
            end_x=240 + (100 if gesture_type == GestureType.SWIPE_RIGHT else -100 if gesture_type == GestureType.SWIPE_LEFT else 0),
            end_y=240 + (100 if gesture_type == GestureType.SWIPE_DOWN else -100 if gesture_type == GestureType.SWIPE_UP else 0),
            duration_ms=100
        )
        if gesture_type in self.callbacks:
            for callback in self.callbacks[gesture_type]:
                callback(gesture)
