#!/usr/bin/env python3
"""
generate_pngs.py — Generate all WineBox brand kit PNGs from SVGs.

Run this on a machine with the required fonts installed:
  - Playfair Display (Regular + Bold)
  - Cormorant Garamond (Regular + SemiBold)
  - Georgia (system fallback)

Requirements:
  pip install cairosvg

Usage:
  cd brand-kit
  python generate_pngs.py

This reads SVGs from svg/ and writes PNGs to png/ and favicon/.
"""

import os
import sys

try:
    import cairosvg
except ImportError:
    print("Error: cairosvg is required. Install with: pip install cairosvg")
    sys.exit(1)

# Paths relative to this script's location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SVG_DIR = os.path.join(SCRIPT_DIR, "svg")
PNG_DIR = os.path.join(SCRIPT_DIR, "png")
FAV_DIR = os.path.join(SCRIPT_DIR, "favicon")

os.makedirs(PNG_DIR, exist_ok=True)
os.makedirs(FAV_DIR, exist_ok=True)

# ── Size definitions ──────────────────────────────────────────
# Icon: square, so output_width = output_height
ICON_SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]

# Logos: width-based (height scales proportionally)
COMPACT_SIZES = [200, 400, 800, 1600]
FULL_SIZES = [400, 800, 1600]

# Favicons: square crops from the icon SVGs
FAVICON_SIZES = [16, 32, 48, 180, 192, 512]

# DPI for sharp rendering (2x for retina-quality output)
DPI = 192


def classify_svg(filename):
    """Determine style from filename."""
    if "logo-full" in filename:
        return "full"
    elif "logo-compact" in filename:
        return "compact"
    elif "icon" in filename:
        return "icon"
    return None


def generate_pngs():
    """Generate PNGs from all SVGs in svg/."""
    svg_files = sorted(f for f in os.listdir(SVG_DIR) if f.endswith(".svg"))

    if not svg_files:
        print(f"No SVGs found in {SVG_DIR}")
        sys.exit(1)

    count = 0
    for svg_file in svg_files:
        style = classify_svg(svg_file)
        if style is None:
            continue

        name = svg_file.replace(".svg", "")
        svg_path = os.path.join(SVG_DIR, svg_file)

        with open(svg_path) as f:
            svg_data = f.read().encode("utf-8")

        if style == "icon":
            sizes = ICON_SIZES
        elif style == "compact":
            sizes = COMPACT_SIZES
        else:
            sizes = FULL_SIZES

        for sz in sizes:
            out_path = os.path.join(PNG_DIR, f"{name}-{sz}w.png")
            cairosvg.svg2png(bytestring=svg_data, write_to=out_path,
                             output_width=sz, dpi=DPI)
            count += 1
            print(f"  {name}-{sz}w.png")

    print(f"\nGenerated {count} PNGs in {PNG_DIR}")
    return count


def generate_favicons():
    """Generate favicon PNGs from the on-cream icon SVG."""
    # Use on-cream icon as favicon source (has background)
    fav_source = os.path.join(SVG_DIR, "winebox-icon-on-cream.svg")

    if not os.path.exists(fav_source):
        # Fall back to light icon
        fav_source = os.path.join(SVG_DIR, "winebox-icon-light.svg")

    if not os.path.exists(fav_source):
        print("Warning: No icon SVG found for favicon generation, skipping.")
        return 0

    with open(fav_source) as f:
        svg_data = f.read().encode("utf-8")

    count = 0
    for sz in FAVICON_SIZES:
        out_path = os.path.join(FAV_DIR, f"favicon-{sz}x{sz}.png")
        cairosvg.svg2png(bytestring=svg_data, write_to=out_path,
                         output_width=sz, output_height=sz, dpi=DPI)
        count += 1
        print(f"  favicon-{sz}x{sz}.png")

    # Apple touch icon (180x180)
    apple_path = os.path.join(FAV_DIR, "apple-touch-icon.png")
    cairosvg.svg2png(bytestring=svg_data, write_to=apple_path,
                     output_width=180, output_height=180, dpi=DPI)
    count += 1
    print(f"  apple-touch-icon.png")

    print(f"\nGenerated {count} favicons in {FAV_DIR}")
    return count


if __name__ == "__main__":
    print("WineBox Brand Kit — PNG Generator")
    print("=" * 40)
    print(f"SVG source: {SVG_DIR}")
    print(f"PNG output: {PNG_DIR}")
    print(f"Favicon output: {FAV_DIR}")
    print(f"DPI: {DPI}")
    print()

    print("Generating PNGs...")
    png_count = generate_pngs()

    print("\nGenerating favicons...")
    fav_count = generate_favicons()

    total = png_count + fav_count
    print(f"\nDone. {total} files generated.")
