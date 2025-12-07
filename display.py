"""
OBD-Gauge Display - Pygame-based for HyperPixel 2.1 Round (480x480)
Uses hardware acceleration for smooth rendering on Pi Zero 2W
"""

import os
import pygame
from pygame import gfxdraw


# Constants
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 480
CENTER_X = 240
CENTER_Y = 240

# Colors (RGB tuples for pygame)
BG_BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
ACCENT = (255, 107, 0)  # Orange
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 150, 255)


class DisplayPygame:
    """
    Pygame display for HyperPixel 2.1 Round.
    Uses hardware acceleration for smooth rendering.
    """

    def __init__(self):
        self.width = SCREEN_WIDTH
        self.height = SCREEN_HEIGHT
        self.screen = None
        self._rawfb = False
        self._clock = None
        self._font_cache = {}

    def initialize(self) -> bool:
        """Initialize pygame display."""
        try:
            self._init_display()
            self._clock = pygame.time.Clock()

            # Clear to black
            self.screen.fill(BG_BLACK)
            self._flip()

            print(f"  Display: pygame ({'rawfb' if self._rawfb else 'hw'})")
            return True
        except Exception as e:
            print(f"Display init error: {e}")
            return False

    def _init_display(self):
        """Initialize pygame display driver."""
        self._rawfb = False

        # Check if we have a DISPLAY env var (X11)
        if os.getenv("DISPLAY"):
            pygame.display.init()
            size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
            if size == (480, 480):
                size = (640, 480)  # Fix for 480x480 mode offset
            self.screen = pygame.display.set_mode(
                size,
                pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE
            )
            return

        # Try various SDL drivers for framebuffer
        for driver in ['kmsdrm', 'fbcon', 'directfb', 'svgalib']:
            os.putenv('SDL_VIDEODRIVER', driver)
            try:
                pygame.display.init()
                size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
                if size == (480, 480):
                    size = (640, 480)
                self.screen = pygame.display.set_mode(
                    size,
                    pygame.FULLSCREEN | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HWSURFACE
                )
                print(f"Using driver: {driver}, size: {size}")
                return
            except pygame.error as e:
                print(f'Driver "{driver}" failed: {e}')
                continue

        # Fallback to raw framebuffer
        print("Falling back to raw framebuffer access")
        self._rawfb = True
        os.putenv('SDL_VIDEODRIVER', 'dummy')
        pygame.display.init()
        self.screen = pygame.Surface((480, 480))

    def _flip(self):
        """Update the display."""
        if self._rawfb:
            fbdev = os.getenv('SDL_FBDEV', '/dev/fb0')
            with open(fbdev, 'wb') as fb:
                fb.write(self.screen.convert(16, 0).get_buffer())
        else:
            pygame.display.flip()

    def clear(self, color=BG_BLACK):
        """Clear screen to a color."""
        self.screen.fill(color)

    def get_font(self, size: int, bold: bool = False) -> pygame.font.Font:
        """Get a font of the specified size (cached)."""
        key = (size, bold)
        if key not in self._font_cache:
            pygame.font.init()
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        self._font_cache[key] = pygame.font.Font(path, size)
                        break
                    except Exception:
                        continue
            else:
                self._font_cache[key] = pygame.font.SysFont(None, size)
        return self._font_cache[key]

    def draw_text_centered(self, y: int, text: str, font_size: int = 20,
                           color=WHITE, bold: bool = False):
        """Draw text centered horizontally at the specified y position."""
        font = self.get_font(font_size, bold)
        text_surface = font.render(text, True, color)
        text_rect = text_surface.get_rect(center=(self.width // 2, y + font_size // 2))
        self.screen.blit(text_surface, text_rect)

    def draw_text(self, x: int, y: int, text: str, font_size: int = 20,
                  color=WHITE, bold: bool = False):
        """Draw text at the specified position."""
        font = self.get_font(font_size, bold)
        text_surface = font.render(text, True, color)
        self.screen.blit(text_surface, (x, y))

    def draw_circle(self, center: tuple, radius: int, color, filled: bool = True):
        """Draw a circle."""
        x, y = int(center[0]), int(center[1])
        if filled:
            gfxdraw.aacircle(self.screen, x, y, radius, color)
            gfxdraw.filled_circle(self.screen, x, y, radius, color)
        else:
            gfxdraw.aacircle(self.screen, x, y, radius, color)

    def draw_rect(self, rect: tuple, color, filled: bool = True, width: int = 1):
        """Draw a rectangle. rect = (x, y, width, height)"""
        if filled:
            pygame.draw.rect(self.screen, color, rect)
        else:
            pygame.draw.rect(self.screen, color, rect, width)

    def render(self):
        """Flip the display buffer."""
        self._flip()

    def tick(self, fps: int = 30):
        """Limit frame rate and return actual FPS."""
        return self._clock.tick(fps)

    def show_message(self, title: str, message: str = ""):
        """Quick helper to show a simple message on screen."""
        self.clear()
        self.draw_text_centered(200, title, font_size=28, bold=True)
        if message:
            self.draw_text_centered(250, message, font_size=18, color=GRAY)
        self.render()

    def cleanup(self):
        """Clean up pygame."""
        pygame.quit()


class MockDisplayPygame(DisplayPygame):
    """Mock display for testing without hardware."""

    def initialize(self) -> bool:
        """Initialize in mock mode."""
        os.putenv('SDL_VIDEODRIVER', 'dummy')
        pygame.display.init()
        self.screen = pygame.Surface((480, 480))
        self._clock = pygame.time.Clock()
        self._rawfb = False
        print("Using mock pygame display")
        return True

    def render(self):
        """Save to file instead of displaying."""
        pygame.image.save(self.screen, '/tmp/obd-gauge-display.png')
