#!/usr/bin/env python3
"""
Generate RS7-themed boot splash for HyperPixel 2.1 Round (480x480)
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import math

def create_carbon_fiber_background(width, height):
    """Create a carbon fiber weave texture"""
    img = Image.new('RGB', (width, height), (20, 20, 22))
    draw = ImageDraw.Draw(img)

    # Create a subtle weave pattern
    weave_size = 6
    for y in range(0, height, weave_size * 2):
        for x in range(0, width, weave_size * 2):
            # Alternating diagonal pattern
            offset = (y // (weave_size * 2)) % 2

            # Dark cell
            base_gray = random.randint(18, 25)
            draw.rectangle([x, y, x + weave_size, y + weave_size],
                         fill=(base_gray, base_gray, base_gray + 2))

            # Slightly lighter cell
            light_gray = random.randint(28, 35)
            draw.rectangle([x + weave_size, y, x + weave_size * 2, y + weave_size],
                         fill=(light_gray, light_gray, light_gray + 2))

            # Alternate for next row
            draw.rectangle([x + weave_size, y + weave_size, x + weave_size * 2, y + weave_size * 2],
                         fill=(base_gray, base_gray, base_gray + 2))
            draw.rectangle([x, y + weave_size, x + weave_size, y + weave_size * 2],
                         fill=(light_gray, light_gray, light_gray + 2))

    # Add a subtle gradient overlay for depth
    gradient = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)

    center_x, center_y = width // 2, height // 2
    max_dist = math.sqrt(center_x**2 + center_y**2)

    for y in range(height):
        for x in range(width):
            dist = math.sqrt((x - center_x)**2 + (y - center_y)**2)
            alpha = int(60 * (dist / max_dist))  # Darker at edges
            gradient.putpixel((x, y), (0, 0, 0, alpha))

    img = Image.alpha_composite(img.convert('RGBA'), gradient)

    return img.convert('RGB')


def create_rs7_splash(width=480, height=480, output_path='splash.png'):
    """Create the RS7 boot splash screen"""

    # Create carbon fiber background
    img = create_carbon_fiber_background(width, height)
    draw = ImageDraw.Draw(img)

    # Audi/RS colors
    silver = (200, 200, 205)
    dark_silver = (140, 140, 145)
    red_accent = (187, 16, 21)  # Audi Sport red

    center_x, center_y = width // 2, height // 2

    # Draw circular border (like the gauge bezel)
    bezel_radius = min(width, height) // 2 - 15
    bezel_thickness = 8

    # Outer bezel ring
    for i in range(bezel_thickness):
        gray = 50 + i * 3
        draw.ellipse([center_x - bezel_radius + i, center_y - bezel_radius + i,
                     center_x + bezel_radius - i, center_y + bezel_radius - i],
                    outline=(gray, gray, gray + 2), width=1)

    # Inner accent ring (red)
    inner_ring_radius = bezel_radius - bezel_thickness - 3
    draw.ellipse([center_x - inner_ring_radius, center_y - inner_ring_radius,
                 center_x + inner_ring_radius, center_y + inner_ring_radius],
                outline=red_accent, width=2)

    # Try to load a nice font, fall back to default
    try:
        # Try system fonts
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        ]
        rs7_font = None
        loading_font = None

        for font_path in font_paths:
            try:
                rs7_font = ImageFont.truetype(font_path, 100)
                loading_font = ImageFont.truetype(font_path, 24)
                break
            except:
                continue

        if rs7_font is None:
            rs7_font = ImageFont.load_default()
            loading_font = ImageFont.load_default()

    except Exception:
        rs7_font = ImageFont.load_default()
        loading_font = ImageFont.load_default()

    # Draw RS7 text with shadow
    rs7_text = "RS7"

    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), rs7_text, font=rs7_font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    text_x = center_x - text_width // 2
    text_y = center_y - text_height // 2 - 30  # Slightly above center

    # Shadow
    draw.text((text_x + 3, text_y + 3), rs7_text, font=rs7_font, fill=(0, 0, 0))

    # Main text with metallic gradient effect (simplified)
    draw.text((text_x, text_y), rs7_text, font=rs7_font, fill=silver)

    # Draw "BOOST GAUGE" subtitle
    subtitle = "BOOST GAUGE"
    sub_bbox = draw.textbbox((0, 0), subtitle, font=loading_font)
    sub_width = sub_bbox[2] - sub_bbox[0]
    sub_x = center_x - sub_width // 2
    sub_y = text_y + text_height + 20

    draw.text((sub_x, sub_y), subtitle, font=loading_font, fill=dark_silver)

    # Loading indicator at bottom
    loading_text = "INITIALIZING..."
    load_bbox = draw.textbbox((0, 0), loading_text, font=loading_font)
    load_width = load_bbox[2] - load_bbox[0]
    load_x = center_x - load_width // 2
    load_y = height - 80

    draw.text((load_x, load_y), loading_text, font=loading_font, fill=dark_silver)

    # Draw loading dots/progress indicator
    dot_y = load_y + 35
    dot_radius = 4
    dot_spacing = 20
    num_dots = 5

    start_x = center_x - (num_dots - 1) * dot_spacing // 2

    for i in range(num_dots):
        x = start_x + i * dot_spacing
        # Gradient from dark to bright to simulate animation freeze frame
        brightness = 60 + i * 35
        color = (brightness, brightness, brightness + 5)
        draw.ellipse([x - dot_radius, dot_y - dot_radius,
                     x + dot_radius, dot_y + dot_radius], fill=color)

    # Draw quattro-inspired bottom accent line
    line_y = height - 25
    line_half_width = 80
    draw.line([center_x - line_half_width, line_y, center_x + line_half_width, line_y],
             fill=red_accent, width=3)

    # Small quattro-style elements
    draw.line([center_x - line_half_width - 15, line_y, center_x - line_half_width - 5, line_y],
             fill=dark_silver, width=2)
    draw.line([center_x + line_half_width + 5, line_y, center_x + line_half_width + 15, line_y],
             fill=dark_silver, width=2)

    # Save the image
    img.save(output_path, 'PNG')
    print(f"Created splash screen: {output_path}")
    return output_path


if __name__ == '__main__':
    create_rs7_splash(480, 480, 'splash.png')
