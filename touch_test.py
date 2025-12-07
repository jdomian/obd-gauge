#!/usr/bin/env python3
"""
Minimal touch test - mirrors the working clock-ytsc.py pattern exactly.
Run this to verify touch hardware works with swipe detection.
"""

from hyperpixel2r import Touch
import time

# Track touch state for gesture detection
touch_start = None
touch_start_time = None
touch_current = None  # Track current position during drag
SWIPE_THRESHOLD = 50

def handle_touch(touch_id, x, y, state):
    global touch_start, touch_start_time, touch_current

    if state:  # Touch down / drag
        # Only set start on FIRST touch (not during drag)
        if touch_start is None:
            touch_start = (x, y)
            touch_start_time = time.time()
            print(f"Touch START at ({x}, {y})")
        # Always update current position
        touch_current = (x, y)
    else:  # Touch up
        if touch_start and touch_current:
            dx = touch_current[0] - touch_start[0]
            dy = touch_current[1] - touch_start[1]
            duration = (time.time() - touch_start_time) * 1000

            print(f"Touch END at {touch_current} - delta: ({dx}, {dy}), duration: {duration:.0f}ms")

            # Detect swipe
            if abs(dx) > SWIPE_THRESHOLD and abs(dx) > abs(dy):
                if dx > 0:
                    print(">>> SWIPE RIGHT <<<")
                else:
                    print(">>> SWIPE LEFT <<<")
            elif abs(dy) > SWIPE_THRESHOLD:
                if dy > 0:
                    print(">>> SWIPE DOWN <<<")
                else:
                    print(">>> SWIPE UP <<<")
            else:
                print(">>> TAP <<<")

        touch_start = None
        touch_start_time = None
        touch_current = None


# Create touch at module level - same as working example
print("Initializing touch...")
touch = Touch()

# Register callback
@touch.on_touch
def on_touch(touch_id, x, y, state):
    handle_touch(touch_id, x, y, state)

print("Touch ready! Try swiping on the screen. Ctrl+C to exit.")
print("-" * 40)

# Keep running
try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nExiting...")
