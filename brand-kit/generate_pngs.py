#!/usr/bin/env python3
"""
generate_pngs.py — Generate all WineBox brand kit PNGs from SVGs.

Uses Playwright (headless Chromium) for high-quality text rendering
with proper anti-aliasing and Google Fonts support. Renders at 2x
device scale then downscales with LANCZOS for crisp output.

Requirements:
  pip install playwright pillow
  playwright install chromium

Usage:
  cd brand-kit
  python generate_pngs.py

This reads SVGs from svg/ and writes PNGs to png/ and favicon/.
"""

import io
import os
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

# Paths relative to this script's location
SCRIPT_DIR = Path(__file__).parent.resolve()
SVG_DIR = SCRIPT_DIR / "svg"
PNG_DIR = SCRIPT_DIR / "png"
FAV_DIR = SCRIPT_DIR / "favicon"

# Size definitions
ICON_SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]
COMPACT_SIZES = [200, 400, 800, 1600]
FULL_SIZES = [400, 800, 1600]
FAVICON_SIZES = [16, 32, 48, 180, 192, 512]

# Render at this multiple then downscale for crisp results
RENDER_SCALE = 2

# Google Fonts link for the brand typefaces
GOOGLE_FONTS_LINK = (
    "https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:ital,wght@0,400;0,700;1,400"
    "&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400"
    "&display=swap"
)


def classify_svg(filename: str) -> str | None:
    """Determine logo style from filename."""
    if "logo-full" in filename:
        return "full"
    elif "logo-compact" in filename:
        return "compact"
    elif "icon" in filename:
        return "icon"
    return None


def get_bg_color(filename: str) -> str:
    """Determine background colour from filename."""
    if "on-cream" in filename:
        return "#FAF7F2"
    elif "on-dark" in filename:
        return "#1A0A10"
    else:
        return "transparent"


def render_svg_to_png(
    page: object,
    svg_content: str,
    output_path: Path,
    width: int,
    height: int,
    bg_color: str = "transparent",
) -> None:
    """Render an SVG to PNG using Playwright's browser engine.

    Renders at 2x the target size then downscales with LANCZOS
    for smooth anti-aliased output.
    """
    bg_css = bg_color if bg_color != "transparent" else "transparent"

    html = f"""<!DOCTYPE html>
<html><head>
<link href="{GOOGLE_FONTS_LINK}" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; }}
  body {{
    background: {bg_css};
    width: {width}px;
    height: {height}px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}
  .logo svg {{
    width: {width}px;
    height: {height}px;
    display: block;
  }}
</style></head>
<body><div class="logo">{svg_content}</div></body></html>"""

    page.set_viewport_size({"width": width, "height": height})
    page.set_content(html)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)

    screenshot = page.screenshot(
        type="png",
        omit_background=(bg_color == "transparent"),
    )

    # Downscale from render resolution to target
    img = Image.open(io.BytesIO(screenshot))
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", optimize=True)


def generate_all() -> int:
    """Generate all PNGs and favicons from SVGs."""
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    FAV_DIR.mkdir(parents=True, exist_ok=True)

    svg_files = sorted(f for f in SVG_DIR.iterdir() if f.suffix == ".svg")
    if not svg_files:
        print(f"No SVGs found in {SVG_DIR}")
        sys.exit(1)

    # SVG aspect ratios (from viewBox)
    aspect_ratios = {
        "icon": (1, 1),        # 100x100
        "compact": (340, 80),  # 4.25:1
        "full": (340, 100),    # 3.4:1
    }

    png_count = 0
    fav_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=RENDER_SCALE)

        # Generate logo/icon PNGs
        print("Generating PNGs...")
        for svg_path in svg_files:
            style = classify_svg(svg_path.name)
            if style is None:
                continue

            name = svg_path.stem
            svg_content = svg_path.read_text()
            bg_color = get_bg_color(svg_path.name)

            if style == "icon":
                sizes = ICON_SIZES
            elif style == "compact":
                sizes = COMPACT_SIZES
            else:
                sizes = FULL_SIZES

            vb_w, vb_h = aspect_ratios[style]

            for sz in sizes:
                out_w = sz
                out_h = round(sz * vb_h / vb_w)
                out_path = PNG_DIR / f"{name}-{sz}w.png"

                render_svg_to_png(page, svg_content, out_path, out_w, out_h, bg_color)
                png_count += 1
                print(f"  {out_path.name}")

        print(f"\nGenerated {png_count} PNGs in {PNG_DIR}")

        # Generate favicons from on-cream icon
        print("\nGenerating favicons...")
        fav_source = SVG_DIR / "winebox-icon-on-cream.svg"
        if not fav_source.exists():
            fav_source = SVG_DIR / "winebox-icon-light.svg"

        if fav_source.exists():
            fav_svg = fav_source.read_text()

            for sz in FAVICON_SIZES:
                out_path = FAV_DIR / f"favicon-{sz}x{sz}.png"
                render_svg_to_png(page, fav_svg, out_path, sz, sz, "#FAF7F2")
                fav_count += 1
                print(f"  {out_path.name}")

            # Apple touch icon
            out_path = FAV_DIR / "apple-touch-icon.png"
            render_svg_to_png(page, fav_svg, out_path, 180, 180, "#FAF7F2")
            fav_count += 1
            print(f"  apple-touch-icon.png")

            print(f"\nGenerated {fav_count} favicons in {FAV_DIR}")
        else:
            print("Warning: No icon SVG found for favicon generation, skipping.")

        # Copy the SVG favicon as-is
        fav_svg_src = SVG_DIR / "winebox-icon-on-cream.svg"
        if fav_svg_src.exists():
            fav_svg_dest = FAV_DIR / "favicon.svg"
            fav_svg_dest.write_text(fav_svg_src.read_text())
            print(f"  favicon.svg (copied)")

        browser.close()

    return png_count + fav_count


if __name__ == "__main__":
    print("WineBox Brand Kit — PNG Generator (Playwright)")
    print("=" * 50)
    print(f"SVG source: {SVG_DIR}")
    print(f"PNG output: {PNG_DIR}")
    print(f"Favicon output: {FAV_DIR}")
    print(f"Render scale: {RENDER_SCALE}x")
    print()

    total = generate_all()
    print(f"\nDone. {total} files generated.")
