#!/usr/bin/env python3
"""
OBD-Gauge - Multi-Gauge Display with Touch Navigation
Pi Zero 2W + HyperPixel 2.1 Round

Swipe left/right to switch between gauges:
1. Boost (PSI)
2. Oil Temperature (°F)
3. Coolant Temperature (°F)
"""

import os
import sys
import signal
import pygame
from pygame import gfxdraw
import math
import time
import threading

# Try to import hyperpixel2r touch
try:
    from hyperpixel2r import Touch
    TOUCH_AVAILABLE = True
except ImportError:
    TOUCH_AVAILABLE = False
    print("Warning: hyperpixel2r not available, touch disabled")


class GaugeConfig:
    """Configuration for a single gauge type."""
    def __init__(self, name, unit, min_val, max_val, zones, simulate_func):
        self.name = name
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self.zones = zones  # List of (end_value, color) tuples
        self.simulate = simulate_func


class MultiGauge:
    def __init__(self):
        self._init_display()
        self.screen.fill((0, 0, 0))
        self._flip()

        self.center = (240, 240)
        self._running = False
        self._clock = pygame.time.Clock()

        # Colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.GRAY = (60, 60, 60)
        self.DARK_GRAY = (30, 30, 30)
        self.ORANGE = (255, 107, 0)
        self.GREEN = (0, 255, 0)
        self.YELLOW = (255, 255, 0)
        self.RED = (255, 0, 0)
        self.BLUE = (0, 150, 255)

        # Gauge configs
        self.gauges = [
            GaugeConfig(
                name="BOOST",
                unit="PSI",
                min_val=-15,
                max_val=25,
                zones=[(-15, 0, self.BLUE), (0, 15, self.GREEN), (15, 25, self.RED)],
                simulate_func=self._simulate_boost
            ),
            GaugeConfig(
                name="OIL TEMP",
                unit="°F",
                min_val=100,
                max_val=300,
                zones=[(100, 180, self.BLUE), (180, 250, self.GREEN), (250, 300, self.RED)],
                simulate_func=self._simulate_oil_temp
            ),
            GaugeConfig(
                name="COOLANT",
                unit="°F",
                min_val=100,
                max_val=260,
                zones=[(100, 160, self.BLUE), (160, 220, self.GREEN), (220, 260, self.RED)],
                simulate_func=self._simulate_coolant_temp
            ),
        ]

        self.current_gauge_idx = 0
        self.current_value = 0.0
        self.target_value = 0.0
        self.smoothing = 0.25

        # Animation
        self.start_angle = 135
        self.sweep_angle = 270

        # Font
        pygame.font.init()
        self._font_large = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        self._font_medium = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        self._font_small = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        self._font_title = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)

        # FPS tracking
        self.frame_count = 0
        self.fps_timer = time.time()
        self.fps = 0

        # Touch handling
        self._touch_start_x = None
        self._touch_start_time = None
        self._init_touch()

    def _init_touch(self):
        """Initialize touch input."""
        if not TOUCH_AVAILABLE:
            return

        try:
            self.touch = Touch(bus=11, i2c_addr=0x15, interrupt_pin=27)

            @self.touch.on_touch
            def handle_touch(touch_id, x, y, state):
                self._process_touch(x, y, state)

            print("Touch initialized (hyperpixel2r)")
        except Exception as e:
            print(f"Touch init failed: {e}")

    def _process_touch(self, x, y, state):
        """Process touch events for swipe detection."""
        if state:  # Touch down
            self._touch_start_x = x
            self._touch_start_time = time.time()
        else:  # Touch up
            if self._touch_start_x is not None:
                dx = x - self._touch_start_x
                duration = time.time() - self._touch_start_time

                # Swipe detection: >50px movement, <500ms duration
                if abs(dx) > 50 and duration < 0.5:
                    if dx < 0:  # Swipe left
                        self._next_gauge()
                    else:  # Swipe right
                        self._prev_gauge()

            self._touch_start_x = None
            self._touch_start_time = None

    def _next_gauge(self):
        """Switch to next gauge."""
        old_idx = self.current_gauge_idx
        self.current_gauge_idx = (self.current_gauge_idx + 1) % len(self.gauges)
        # Reset value for new gauge
        gauge = self.gauges[self.current_gauge_idx]
        self.current_value = gauge.min_val
        self.target_value = gauge.min_val
        print(f"Switched to: {gauge.name}")

    def _prev_gauge(self):
        """Switch to previous gauge."""
        old_idx = self.current_gauge_idx
        self.current_gauge_idx = (self.current_gauge_idx - 1) % len(self.gauges)
        # Reset value for new gauge
        gauge = self.gauges[self.current_gauge_idx]
        self.current_value = gauge.min_val
        self.target_value = gauge.min_val
        print(f"Switched to: {gauge.name}")

    def _exit(self, sig, frame):
        self._running = False
        print("\nExiting!...\n")

    def _init_display(self):
        self._rawfb = False

        if os.getenv('SDL_VIDEODRIVER'):
            print(f"Using driver: {os.getenv('SDL_VIDEODRIVER')}")
            pygame.display.init()
            size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
            if size == (480, 480):
                size = (640, 480)
            self.screen = pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE)
            return

        for driver in ['kmsdrm', 'fbcon', 'directfb', 'svgalib']:
            os.putenv('SDL_VIDEODRIVER', driver)
            try:
                pygame.display.init()
                size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
                if size == (480, 480):
                    size = (640, 480)
                self.screen = pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE)
                print(f"Using driver: {driver}, size: {size}")
                return
            except pygame.error as e:
                print(f'Driver "{driver}" failed: {e}')
                continue

        print("Falling back to raw framebuffer")
        self._rawfb = True
        os.putenv('SDL_VIDEODRIVER', 'dummy')
        pygame.display.init()
        self.screen = pygame.Surface((480, 480))

    def _flip(self):
        if self._rawfb:
            fbdev = os.getenv('SDL_FBDEV', '/dev/fb0')
            with open(fbdev, 'wb') as fb:
                fb.write(self.screen.convert(16, 0).get_buffer())
        else:
            pygame.display.flip()

    def _get_point(self, origin, angle, distance):
        r = math.radians(angle)
        x = origin[0] + distance * math.cos(r)
        y = origin[1] + distance * math.sin(r)
        return int(x), int(y)

    def _draw_arc(self, center, radius, start_angle, end_angle, color, thickness=3):
        for angle in range(int(start_angle), int(end_angle), 2):
            x1, y1 = self._get_point(center, angle, radius)
            x2, y2 = self._get_point(center, angle + 2, radius)
            pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), thickness)

    def _value_to_angle(self, value, gauge):
        """Convert a value to needle angle for given gauge."""
        val_range = gauge.max_val - gauge.min_val
        val_normalized = (value - gauge.min_val) / val_range
        val_normalized = max(0, min(1, val_normalized))  # Clamp
        return self.start_angle + (val_normalized * self.sweep_angle)

    def _draw_needle(self, value, gauge):
        """Draw the gauge needle."""
        angle = self._value_to_angle(value, gauge)

        tip = self._get_point(self.center, angle, 160)
        base_left = self._get_point(self.center, angle + 90, 15)
        base_right = self._get_point(self.center, angle - 90, 15)
        tail = self._get_point(self.center, angle + 180, 30)

        pygame.draw.polygon(self.screen, self.RED, [tip, base_left, tail, base_right])
        pygame.draw.polygon(self.screen, self.WHITE, [tip, base_left, tail, base_right], 2)

        gfxdraw.aacircle(self.screen, 240, 240, 20, self.GRAY)
        gfxdraw.filled_circle(self.screen, 240, 240, 20, self.GRAY)
        gfxdraw.aacircle(self.screen, 240, 240, 10, self.WHITE)
        gfxdraw.filled_circle(self.screen, 240, 240, 10, self.WHITE)

    def _draw_gauge_face(self, gauge):
        """Draw the gauge face for current gauge type."""
        # Outer ring
        gfxdraw.aacircle(self.screen, 240, 240, 220, self.GRAY)
        gfxdraw.aacircle(self.screen, 240, 240, 218, self.GRAY)

        # Draw colored arc zones
        for zone_start, zone_end, color in gauge.zones:
            start_angle = self._value_to_angle(zone_start, gauge)
            end_angle = self._value_to_angle(zone_end, gauge)
            self._draw_arc(self.center, 190, start_angle, end_angle, color, 8)

        # Calculate tick spacing based on range
        val_range = gauge.max_val - gauge.min_val
        if val_range <= 50:
            major_step = 5
            minor_step = 1
        elif val_range <= 100:
            major_step = 10
            minor_step = 5
        else:
            major_step = 20
            minor_step = 10

        # Major ticks and labels
        val = gauge.min_val
        while val <= gauge.max_val:
            angle = self._value_to_angle(val, gauge)

            inner = self._get_point(self.center, angle, 165)
            outer = self._get_point(self.center, angle, 185)
            pygame.draw.line(self.screen, self.WHITE, inner, outer, 3)

            label_pos = self._get_point(self.center, angle, 140)
            label = self._font_small.render(str(int(val)), True, self.WHITE)
            label_rect = label.get_rect(center=label_pos)
            self.screen.blit(label, label_rect)

            val += major_step

        # Minor ticks
        val = gauge.min_val
        while val <= gauge.max_val:
            if val % major_step != 0:
                angle = self._value_to_angle(val, gauge)
                inner = self._get_point(self.center, angle, 175)
                outer = self._get_point(self.center, angle, 185)
                pygame.draw.line(self.screen, self.GRAY, inner, outer, 1)
            val += minor_step

    def _draw_digital_readout(self, value, gauge):
        """Draw digital readout."""
        pygame.draw.rect(self.screen, self.GRAY, (170, 300, 140, 60))
        pygame.draw.rect(self.screen, self.WHITE, (170, 300, 140, 60), 2)

        # Determine color based on zones
        color = self.WHITE
        for zone_start, zone_end, zone_color in gauge.zones:
            if zone_start <= value <= zone_end:
                color = zone_color
                break

        # Format value
        if gauge.unit == "PSI":
            if value >= 0:
                text = f"+{value:.1f}"
            else:
                text = f"{value:.1f}"
        else:
            text = f"{value:.0f}"

        val_surface = self._font_medium.render(text, True, color)
        val_rect = val_surface.get_rect(center=(240, 330))
        self.screen.blit(val_surface, val_rect)

        unit_surface = self._font_small.render(gauge.unit, True, self.WHITE)
        unit_rect = unit_surface.get_rect(center=(240, 375))
        self.screen.blit(unit_surface, unit_rect)

    def _draw_title(self, gauge):
        """Draw gauge name at top."""
        title_surface = self._font_title.render(gauge.name, True, self.ORANGE)
        title_rect = title_surface.get_rect(center=(240, 50))
        self.screen.blit(title_surface, title_rect)

    def _draw_page_dots(self):
        """Draw page indicator dots at bottom."""
        dot_y = 450
        dot_spacing = 20
        total_width = (len(self.gauges) - 1) * dot_spacing
        start_x = 240 - total_width // 2

        for i in range(len(self.gauges)):
            x = start_x + i * dot_spacing
            if i == self.current_gauge_idx:
                gfxdraw.aacircle(self.screen, x, dot_y, 5, self.WHITE)
                gfxdraw.filled_circle(self.screen, x, dot_y, 5, self.WHITE)
            else:
                gfxdraw.aacircle(self.screen, x, dot_y, 4, self.GRAY)
                gfxdraw.filled_circle(self.screen, x, dot_y, 4, self.GRAY)

    def _draw_fps(self):
        fps_text = f"FPS: {self.fps:.1f}"
        fps_surface = self._font_small.render(fps_text, True, self.YELLOW)
        self.screen.blit(fps_surface, (10, 10))

    def _draw_swipe_hint(self):
        """Draw swipe hint arrows."""
        # Left arrow
        if self.current_gauge_idx > 0:
            pygame.draw.polygon(self.screen, self.DARK_GRAY, [(20, 240), (35, 225), (35, 255)])
        # Right arrow
        if self.current_gauge_idx < len(self.gauges) - 1:
            pygame.draw.polygon(self.screen, self.DARK_GRAY, [(460, 240), (445, 225), (445, 255)])

    def _update_value(self, target, dt):
        diff = target - self.current_value
        ease_factor = 1.0 - math.pow(1.0 - self.smoothing, dt * 60)
        self.current_value += diff * ease_factor
        if abs(diff) < 0.01:
            self.current_value = target

    # Simulation functions
    def _simulate_boost(self, t):
        cycle = t % 8
        if cycle < 2:
            return -12 + math.sin(t * 3) * 2
        elif cycle < 3:
            progress = (cycle - 2)
            return -12 + (progress * 35)
        elif cycle < 5:
            return 20 + math.sin(t * 10) * 3
        elif cycle < 6:
            progress = (cycle - 5)
            return 20 - (progress * 25)
        else:
            progress = (cycle - 6) / 2
            return -5 - (progress * 7)

    def _simulate_oil_temp(self, t):
        # Warm up then stabilize
        base = min(220, 140 + t * 2)  # Warm up over time
        fluctuation = math.sin(t * 0.5) * 5
        return base + fluctuation

    def _simulate_coolant_temp(self, t):
        # Similar to oil but different curve
        base = min(195, 120 + t * 3)
        fluctuation = math.sin(t * 0.3) * 3
        return base + fluctuation

    def run(self, target_fps=30, obd_rate=25):
        self._running = True
        signal.signal(signal.SIGINT, self._exit)

        start_time = time.time()
        last_frame_time = start_time
        last_obd_time = start_time
        obd_interval = 1.0 / obd_rate

        gauge = self.gauges[self.current_gauge_idx]
        self.current_value = gauge.min_val
        self.target_value = gauge.min_val

        print(f"Starting multi-gauge display at {target_fps} FPS...")
        print(f"Gauges: {', '.join(g.name for g in self.gauges)}")
        print("Swipe left/right to change gauges")
        print("Press Ctrl+C to stop")

        while self._running:
            current_time = time.time()
            dt = current_time - last_frame_time
            last_frame_time = current_time

            gauge = self.gauges[self.current_gauge_idx]

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    break
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._running = False
                        break
                    elif event.key == pygame.K_LEFT:
                        self._prev_gauge()
                    elif event.key == pygame.K_RIGHT:
                        self._next_gauge()

            # Simulate OBD2 data
            if current_time - last_obd_time >= obd_interval:
                t = current_time - start_time
                self.target_value = gauge.simulate(t)
                last_obd_time = current_time

            self._update_value(self.target_value, dt)

            # Draw
            self.screen.fill(self.BLACK)
            self._draw_gauge_face(gauge)
            self._draw_needle(self.current_value, gauge)
            self._draw_digital_readout(self.current_value, gauge)
            self._draw_title(gauge)
            self._draw_page_dots()
            self._draw_swipe_hint()
            self._draw_fps()

            self._flip()

            # FPS tracking
            self.frame_count += 1
            if time.time() - self.fps_timer >= 1.0:
                self.fps = self.frame_count / (time.time() - self.fps_timer)
                self.frame_count = 0
                self.fps_timer = time.time()

            self._clock.tick(target_fps)

        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Gauge Display with Touch Navigation")
    parser.add_argument('--fps', type=int, default=30, help='Target FPS')
    parser.add_argument('--obd', type=int, default=25, help='OBD2 data rate Hz')
    parser.add_argument('--smooth', type=float, default=0.25, help='Smoothing factor')
    args = parser.parse_args()

    app = MultiGauge()
    app.smoothing = args.smooth
    app.run(target_fps=args.fps, obd_rate=args.obd)
