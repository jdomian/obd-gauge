#!/usr/bin/env python3
"""
Generate pre-rendered raw framebuffer file for instant boot splash.
Run once to create splash.raw, then boot script just copies it to /dev/fb0.
"""

from PIL import Image
import os
import sys

def to_rgb565(r, g, b):
    """Convert RGB888 to RGB565"""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

def generate_raw(image_path='splash.png', output_path='splash.raw'):
    """Convert PNG to raw framebuffer format with HyperPixel stride"""

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

    # Write raw file
    with open(output_path, 'wb') as f:
        f.write(buffer)

    print(f'Generated {output_path} ({len(buffer)} bytes)')
    return output_path

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(script_dir, 'splash.png')
    output_path = os.path.join(script_dir, 'splash.raw')

    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    if len(sys.argv) > 2:
        output_path = sys.argv[2]

    generate_raw(image_path, output_path)
