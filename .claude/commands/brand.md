# WineBox Brand Guidelines

Brand identity assets and guidelines for **WineBox** (winebox.app) — a wine cellar collection app.

When creating any visual asset, page, component, document, or presentation for this project, follow these guidelines and use the assets from the `brand-kit/` directory.

## Brand Kit Contents

The `brand-kit/` directory lives at the project root and contains:

```
brand-kit/
├── index.html                          ← Interactive brand kit web page (open in browser)
├── BRAND.md                            ← This file
├── svg/                                ← 12 vector logos (infinitely scalable)
│   ├── winebox-logo-full-light.svg       Full logo, light theme, transparent
│   ├── winebox-logo-full-dark.svg        Full logo, dark theme, transparent
│   ├── winebox-logo-full-on-cream.svg    Full logo on cream (#FAF7F2) background
│   ├── winebox-logo-full-on-dark.svg     Full logo on dark (#1A0A10) background
│   ├── winebox-logo-compact-light.svg    Compact logo (icon + wordmark), light, transparent
│   ├── winebox-logo-compact-dark.svg     Compact logo, dark, transparent
│   ├── winebox-logo-compact-on-cream.svg Compact logo on cream background
│   ├── winebox-logo-compact-on-dark.svg  Compact logo on dark background
│   ├── winebox-icon-light.svg            Icon only, light theme, transparent
│   ├── winebox-icon-dark.svg             Icon only, dark theme, transparent
│   ├── winebox-icon-on-cream.svg         Icon on cream background
│   └── winebox-icon-on-dark.svg          Icon on dark background
├── png/                                ← 64 pre-rendered PNGs
│   ├── winebox-icon-{light,dark,on-cream,on-dark}-{16,32,48,64,128,180,192,256,512,1024}w.png
│   ├── winebox-logo-compact-{light,dark,on-cream,on-dark}-{200,400,800}w.png
│   └── winebox-logo-full-{light,dark,on-cream,on-dark}-{400,800,1600}w.png
└── favicon/                            ← 8 favicon & app icon files
    ├── favicon.svg                       Vector favicon for modern browsers
    ├── favicon-16x16.png                 Classic favicon
    ├── favicon-32x32.png                 HiDPI favicon
    ├── favicon-48x48.png                 Windows taskbar
    ├── favicon-180x180.png               iOS / Android large
    ├── favicon-192x192.png               Android / PWA manifest
    ├── favicon-512x512.png               PWA splash screen
    └── apple-touch-icon.png              iOS home screen (180×180, cream bg)
```

## Brand Identity

### Logo Concept

Three wine bottles sitting in an open wooden case. Simple, recognisable at any size. The icon uses warm wood tones for the case and deep burgundy-pink for the bottles, with subtle gold labels.

### Logo Variants

| Variant       | Use Case                                      | SVG Dimensions |
|---------------|-----------------------------------------------|----------------|
| **Full**      | Website headers, hero sections, documents     | 520 × 120      |
| **Compact**   | Navigation bars, sidebars, mobile headers     | 340 × 80       |
| **Icon**      | App icons, favicons, avatars, social profiles | 100 × 100      |

Each variant has four versions:
- **light** — for use on dark backgrounds (transparent)
- **dark** — for use on light backgrounds (transparent)
- **on-cream** — baked cream (#FAF7F2) background
- **on-dark** — baked dark (#1A0A10) background

**Rule:** Always use `light` theme assets on dark backgrounds and `dark` theme assets on light backgrounds. The `on-cream` and `on-dark` versions are for contexts where transparency is not supported (e.g. OG images, email headers).

### Colour Palette

| Name           | Hex       | CSS Variable        | Usage                          |
|----------------|-----------|----------------------|--------------------------------|
| Burgundy       | `#5C0A2D` | `--burgundy`         | Primary brand colour           |
| Burgundy Light | `#8B1A4A` | `--burgundy-light`   | Hover states, accents          |
| Bottle         | `#B82860` | `--bottle`           | Icon bottle fill, highlights   |
| Gold           | `#C49A3C` | `--gold`             | Wordmark accent "Box", labels  |
| Gold Light     | `#F0D78C` | `--gold-light`       | Light accents, label fills     |
| Case Wood      | `#B8956A` | `--case-wood`        | Icon case fill, warmth         |
| Cream          | `#FAF7F2` | `--cream`            | Light backgrounds              |
| Dark           | `#1A0A10` | `--dark-bg`          | Dark backgrounds               |

Always define CSS variables for these colours at the `:root` level and reference variables throughout.

### Typography

| Typeface              | Weight(s)  | Usage                                  | Google Fonts Import                                |
|-----------------------|------------|----------------------------------------|----------------------------------------------------|
| **Playfair Display**  | 400, 700   | Wordmark, headlines, section titles    | `Playfair+Display:ital,wght@0,400;0,700;1,400`    |
| **Cormorant Garamond**| 400, 600   | Taglines, captions, labels, quotes     | `Cormorant+Garamond:ital,wght@0,400;0,600;1,400`  |
| **DM Sans**           | 400, 500, 600 | Body text, buttons, navigation, forms | `DM+Sans:wght@400;500;600`                         |

**Wordmark rule:** "Wine" is Playfair Display Bold (`#5C0A2D` on light / `#E0C0CC` on dark) and "Box" is Playfair Display Regular in gold (`#C49A3C` on light / `#F0D78C` on dark).

**Tagline:** "YOUR CELLAR, CURATED" — Cormorant Garamond italic, 12–14px, letter-spacing 4–6px, uppercase.

### Dark Theme Text Colours

When placing text on dark backgrounds:
- Wine text: `#E0C0CC`
- Box text: `#F0D78C`
- Tagline: `#C8A0B0`
- Body text: `#A08898`

## Implementation Reference

### CSS variable setup

Every WineBox page or component should start with:

```css
:root {
  --burgundy: #5C0A2D;
  --burgundy-light: #8B1A4A;
  --bottle: #B82860;
  --gold: #C49A3C;
  --gold-light: #F0D78C;
  --case-wood: #B8956A;
  --cream: #FAF7F2;
  --dark-bg: #1A0A10;
  --text: #2D1A22;
  --text-muted: #8A7A80;
  --border: #E8E0D8;
}
```

### Google Fonts import

```html
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
```

### Embedding logos in HTML

Always prefer SVG for web use. Reference from the project root:

```html
<!-- Full logo in a header -->
<img src="/brand-kit/svg/winebox-logo-full-light.svg" alt="WineBox" height="60">

<!-- Icon in a nav bar -->
<img src="/brand-kit/svg/winebox-icon-light.svg" alt="WineBox" width="40" height="40">
```

### Favicon implementation

Copy `brand-kit/favicon/` contents to the site root and add:

```html
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
```

### PWA manifest icons

```json
{
  "icons": [
    { "src": "/favicon-192x192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/favicon-512x512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

### Choosing the right PNG

| Context                        | Recommended File                            |
|--------------------------------|---------------------------------------------|
| Favicon (browser tab)          | `favicon/favicon-32x32.png`                 |
| iOS home screen                | `favicon/apple-touch-icon.png`              |
| Android / PWA                  | `favicon/favicon-192x192.png`               |
| Social media avatar            | `png/winebox-icon-on-cream-256w.png`        |
| OG / social share image        | `png/winebox-logo-full-on-cream-800w.png`   |
| Email header                   | `png/winebox-logo-compact-light-400w.png`   |
| Presentation slide             | `png/winebox-logo-full-light-800w.png`      |
| Print (high-res)               | `png/winebox-logo-full-light-1600w.png` or SVG |
| App splash / about screen      | `png/winebox-icon-light-512w.png`           |

### Inserting into documents (DOCX, PPTX, PDF)

When creating branded documents, copy the appropriate PNG from `brand-kit/` into the working directory and embed it:

```python
# Example: inserting logo into a python-docx document
from docx import Document
from docx.shared import Inches
import shutil

shutil.copy('brand-kit/png/winebox-logo-full-light-800w.png', '/home/claude/logo.png')

doc = Document()
doc.add_picture('/home/claude/logo.png', width=Inches(4))
```

For presentations, use the compact or icon variant depending on slide layout. For PDFs, prefer SVG where the library supports it, otherwise use the 800w or 1600w PNG.

## Usage Rules

### Do

- Maintain clear space around the logo equal to at least the height of one bottle in the icon
- Use the correct theme variant for the background (light-on-dark, dark-on-light)
- Scale proportionally — always preserve aspect ratio
- Use SVG wherever possible for crisp rendering at any size
- Use CSS variables for all brand colours — never hard-code hex values in component styles

### Do Not

- Alter, substitute, or approximate the brand colours
- Add drop shadows, bevels, outlines, glows, or extra gradients to the logo
- Stretch, skew, rotate, or partially crop the logo
- Place the light-theme logo on a light background or vice versa
- Use the logo at sizes below 32px without switching to the icon-only variant
- Recreate or redraw the logo — always use the official assets from this kit
