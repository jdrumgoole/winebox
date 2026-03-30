# WineBox Brand Guidelines

> When working on the WineBox project, follow these guidelines to maintain brand consistency.

## Brand Identity

- **Name**: WineBox
- **Tagline**: YOUR CELLAR, CURATED.
- **Website**: https://winebox.app
- **Description**: AI-powered wine cellar management

## Logo Description

The WineBox icon depicts **three wine bottles of varying height in an open wooden case**. The bottles use curved path shapes (not simple rectangles) with a distinctive rose-burgundy fill (`#B82860`) and semi-transparent golden labels (`#F0D78C` at 45% opacity). The wooden case has horizontal grain lines and vertical dividers.

The wordmark uses a **two-tone treatment**: "Wine" is bold, "Box" is regular weight, in contrasting colours from the brand palette.

## Colour Palette

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Burgundy | `#5C0A2D` | 92, 10, 45 | Footer, nav gradient end, "Wine" text (light) |
| Burgundy Light | `#8B1A4A` | 139, 26, 74 | Headings, nav gradient start, CTA gradient |
| Rose | `#B82860` | 184, 40, 96 | Bottle fill in icon |
| Gold | `#C49A3C` | 196, 154, 60 | CTA buttons, "Box" text (light), accents |
| Gold Light | `#F0D78C` | 240, 215, 140 | Bottle labels, "Box" text (dark) |
| Case Wood | `#B8956A` | 184, 149, 106 | Case fill (light theme) |
| Case Wood Dark | `#A08060` | 160, 128, 96 | Case fill (dark theme) |
| Case Stroke | `#8A6C4E` | 138, 108, 78 | Case stroke & vertical dividers |
| Case Grain | `#907050` | 144, 112, 80 | Case grain lines |
| Cream | `#FAF7F2` | 250, 247, 242 | Page background |
| Cream Dark | `#F0EBE3` | 240, 235, 227 | Hero gradient end |
| Dark BG | `#1A0A10` | 26, 10, 16 | Dark mode background |
| Body Text | `#666666` | 102, 102, 102 | Paragraph text |

### Key Gradients

- **Nav / CTA**: `linear-gradient(135deg, #8B1A4A 0%, #5C0A2D 100%)`
- **Hero section**: `linear-gradient(135deg, #FAF7F2 0%, #F0EBE3 100%)`

## Typography

| Role | Font | Weight | Fallback |
|------|------|--------|----------|
| Wordmark | Playfair Display | 700 "Wine" / 400 "Box" | Georgia, serif |
| Tagline / Subtitles | Cormorant Garamond | 400 / 600 | Georgia, serif |
| Headings / Body / UI | System font stack | 400 / 500 / 700 | -apple-system, system-ui, Segoe UI, sans-serif |

The site uses **system fonts** for headings and body text (not a custom font). Only the logo wordmark and tagline/subtitles use serif fonts.

Google Fonts import (for logo rendering contexts):
```
https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Cormorant+Garamond:wght@400;600&display=swap
```

## Logo Variants

### Styles
- **Icon**: Three bottles in case, standalone
- **Compact**: Icon + "WineBox" wordmark (used in site header)
- **Full**: Icon + "WineBox" wordmark + tagline

### Themes
- **light**: Dark elements on transparent background (for light pages)
- **dark**: Light/cream elements on transparent background (for dark/burgundy backgrounds)
- **on-cream**: Light theme on cream (`#FAF7F2`) background
- **on-dark**: Dark theme on dark (`#1A0A10`) background

### File naming
```
winebox-{style}-{theme}.svg
winebox-{style}-{theme}-{width}w.png
```

### Existing site assets
The live site currently uses:
- `/static/logos/logo-compact-dark.svg` — header logo (on burgundy nav)
- `/static/logos/logo-compact-light.svg` — footer logo variant

## Generating PNGs

The kit ships as SVGs only. To generate PNGs and favicon PNGs, run:

```bash
cd brand-kit
pip install cairosvg
python generate_pngs.py
```

This requires **Playfair Display** and **Cormorant Garamond** fonts installed on the system (available from Google Fonts). The script generates PNGs in `png/` and favicons in `favicon/` at standard sizes with 192 DPI for retina-quality output.

## Favicon Files

Located in `brand-kit/favicon/`:
- `favicon.svg` — vector favicon (icon, light theme)
- `favicon-{16,32,48,180,192,512}x{size}.png`
- `apple-touch-icon.png` (180×180)

### HTML snippet
```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32x32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
```

## UI Patterns

### Buttons
- **Primary CTA**: `background: #C49A3C`, white text, `border-radius: 8px`
- **Outline**: `border: 1px solid #8B1A4A`, transparent bg, burgundy text, `border-radius: 8px`
- **On dark**: `border: 1px solid rgba(255,255,255,0.5)`, transparent bg, white text

### Feature cards
- Cream background with subtle border
- Burgundy icon containers with `border-radius: 8px`
- System font stack for all card text

### Border radius
- Buttons: `8px`
- Cards: `12px`
- Logo case: `4px`

## Usage Rules

### Do
- Scale the logo proportionally
- Use SVG wherever possible for crisp rendering
- Maintain clear space equal to the icon height around the logo
- Use the `dark` theme on burgundy/dark backgrounds
- Use the `light` theme on cream/white backgrounds

### Don't
- Alter the brand colours
- Add drop shadows, bevels, outlines, or gradients to the logo
- Distort, skew, rotate, or crop the logo
- Place the logo on busy or clashing backgrounds
- Change the two-tone "Wine"/"Box" colour treatment
