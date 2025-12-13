#!/usr/bin/env python3
"""
Show splash screen on HyperPixel 2.1 Round display.
Handles the 720x480 virtual / 480x480 physical framebuffer correctly.
"""

from PIL import Image
import os
import sys

def to_rgb565(r, g, b):
    """Convert RGB888 to RGB565"""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

def show_splash(image_path='/home/claude/obd-gauge/splash.png'):
    """Write splash image directly to framebuffer with correct stride"""

    # Load and convert image
    img = Image.open(image_path)
    img = img.convert('RGB')

    # Resize if needed (must be 480x480)
    if img.size != (480, 480):
        img = img.resize((480, 480), Image.LANCZOS)

    # HyperPixel 2r: 720 stride, 480 visible width, 16bpp
    fb_stride = 720 * 2  # bytes per row (720 pixels * 2 bytes)
    screen_width = 480
    screen_height = 480

    # Build padded framebuffer
    buffer = bytearray(fb_stride * screen_height)

    for y in range(screen_height):
        for x in range(screen_width):
            r, g, b = img.getpixel((x, y))
            pixel = to_rgb565(r, g, b)
            offset = y * fb_stride + x * 2
            buffer[offset] = pixel & 0xFF
            buffer[offset + 1] = (pixel >> 8) & 0xFF

    # Write to framebuffer
    fbdev = os.environ.get('SDL_FBDEV', '/dev/fb0')
    with open(fbdev, 'wb') as fb:
        fb.write(buffer)

    print(f'Splash written to {fbdev}')

if __name__ == '__main__':
    image_path = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/obd-gauge/splash.png'
    show_splash(image_path)
