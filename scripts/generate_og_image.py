"""Generate an Open Graph image (1200x627) for social media previews.

Uses only Pillow — no system dependencies required. Draws a branded
OG image with the WineBox icon (wine bottles in a crate) and text.
"""

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Required package: pip install Pillow")
    sys.exit(1)


# Brand colors from landing.css
PRIMARY = "#8B1A4A"
PRIMARY_DARK = "#5C0A2D"
SECONDARY = "#C49A3C"
BACKGROUND = "#FAF7F2"
TEXT_COLOR = "#2c2c2c"
CRATE_COLOR = "#B8956A"
CRATE_DARK = "#9A7B54"

WIDTH = 1200
HEIGHT = 627


def draw_wine_bottle(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    """Draw a simplified wine bottle centered at (cx, cy)."""
    s = scale

    # Bottle body
    body_w = int(16 * s)
    body_h = int(38 * s)
    body_left = cx - body_w // 2
    body_top = cy - int(5 * s)
    draw.rounded_rectangle(
        [(body_left, body_top), (body_left + body_w, body_top + body_h)],
        radius=int(3 * s),
        fill=PRIMARY,
    )

    # Neck
    neck_w = int(8 * s)
    neck_h = int(20 * s)
    neck_left = cx - neck_w // 2
    neck_top = body_top - neck_h + int(5 * s)
    draw.rounded_rectangle(
        [(neck_left, neck_top), (neck_left + neck_w, neck_top + neck_h)],
        radius=int(2 * s),
        fill=PRIMARY,
    )

    # Cork
    cork_w = int(6 * s)
    cork_h = int(6 * s)
    cork_left = cx - cork_w // 2
    cork_top = neck_top - cork_h + int(2 * s)
    draw.rounded_rectangle(
        [(cork_left, cork_top), (cork_left + cork_w, cork_top + cork_h)],
        radius=int(1 * s),
        fill=CRATE_COLOR,
    )

    # Label
    label_w = int(13 * s)
    label_h = int(14 * s)
    label_left = cx - label_w // 2
    label_top = body_top + int(6 * s)
    draw.rounded_rectangle(
        [(label_left, label_top), (label_left + label_w, label_top + label_h)],
        radius=int(1 * s),
        fill=SECONDARY,
        outline=CRATE_DARK,
        width=1,
    )


def draw_crate(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    """Draw a wine crate with 3 bottles."""
    s = scale

    # Crate body
    crate_w = int(92 * s)
    crate_h = int(45 * s)
    crate_left = cx - crate_w // 2
    crate_top = cy
    draw.rounded_rectangle(
        [(crate_left, crate_top), (crate_left + crate_w, crate_top + crate_h)],
        radius=int(4 * s),
        fill=CRATE_COLOR,
        outline=CRATE_DARK,
        width=int(2 * s),
    )

    # Crate horizontal dividers
    for y_offset in [int(15 * s), int(30 * s)]:
        y = crate_top + y_offset
        draw.line(
            [(crate_left + int(2 * s), y), (crate_left + crate_w - int(2 * s), y)],
            fill=CRATE_DARK,
            width=1,
        )

    # Crate vertical dividers
    for x_offset in [int(31 * s), int(61 * s)]:
        x = crate_left + x_offset
        draw.line(
            [(x, crate_top + int(4 * s)), (x, crate_top + crate_h - int(4 * s))],
            fill=CRATE_DARK,
            width=1,
        )

    # Draw 3 bottles poking out of the crate
    bottle_y = crate_top - int(5 * s)
    for i in range(3):
        bx = crate_left + int(15 * s) + i * int(30 * s)
        draw_wine_bottle(draw, bx, bottle_y, scale=s * 0.9)


def generate_og_image(output_path: Path) -> None:
    """Generate the OG image and save it."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(img)

    # Top accent bar
    draw.rectangle([(0, 0), (WIDTH, 8)], fill=PRIMARY)

    # Bottom accent bar
    draw.rectangle([(0, HEIGHT - 6), (WIDTH, HEIGHT)], fill=SECONDARY)

    # Draw the wine crate icon on the left side
    crate_cx = 320
    crate_cy = HEIGHT // 2 - 20
    draw_crate(draw, crate_cx, crate_cy, scale=2.2)

    # Load fonts
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 80)
        tagline_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 30)
    except (OSError, IOError):
        try:
            title_font = ImageFont.truetype("/System/Library/Fonts/Georgia.ttf", 80)
            tagline_font = ImageFont.truetype("/System/Library/Fonts/Georgia.ttf", 30)
        except (OSError, IOError):
            try:
                title_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 80
                )
                tagline_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 30
                )
            except (OSError, IOError):
                title_font = ImageFont.load_default()
                tagline_font = ImageFont.load_default()

    # Draw title text
    text_x = 560
    title_y = HEIGHT // 2 - 70
    draw.text((text_x, title_y), "WineBox", fill=PRIMARY, font=title_font)

    # Draw tagline
    tagline_y = title_y + 100
    draw.text(
        (text_x, tagline_y),
        "Smart Wine Cellar\nManagement",
        fill=TEXT_COLOR,
        font=tagline_font,
        spacing=8,
    )

    # Draw subtle URL at bottom
    try:
        url_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 22)
    except (OSError, IOError):
        try:
            url_font = ImageFont.truetype("/System/Library/Fonts/Georgia.ttf", 22)
        except (OSError, IOError):
            url_font = tagline_font

    draw.text(
        (text_x, HEIGHT - 60),
        "winebox.app",
        fill="#999999",
        font=url_font,
    )

    img.save(output_path, "PNG", optimize=True)
    print(f"Generated OG image: {output_path} ({WIDTH}x{HEIGHT})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OG image for WineBox")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).parent.parent
        / "winebox"
        / "static"
        / "logos"
        / "og-image.png",
        help="Output path (default: winebox/static/logos/og-image.png)",
    )
    args = parser.parse_args()
    generate_og_image(args.output)


if __name__ == "__main__":
    main()
