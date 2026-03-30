# WineBox Brand Kit

Complete, professional brand guidelines and logo assets for WineBox (winebox.app) - ready for use in development, marketing, partnerships, and print media.

## 📦 What's Included

This brand kit contains everything needed to maintain consistent WineBox branding across all channels:

- **Logo Files (SVG)** - Scalable, crisp at any size
  - Horizontal lockup (logo + wordmark)
  - Icon/symbol (square)
  - Monochrome versions (single color)

- **Export Specifications** - Detailed guides for every use case
  - Web (digital, responsive, retina)
  - Print (300 DPI professional quality)
  - Social media (LinkedIn, Instagram, Twitter, Facebook)
  - Email signatures
  - Favicons and app icons
  - Business cards, letterhead, posters

- **Brand Guidelines** - Comprehensive style documentation
  - Color palette with hex codes
  - Typography specifications
  - Voice and tone guidelines
  - Photography and imagery standards
  - Clear space and minimum sizes
  - Usage rules and what not to do

- **Export Automation** - Python utility for generating all variants
  - Batch generation of PNG files at all required sizes
  - Web-optimized assets
  - Print-quality 300 DPI versions
  - Social media pre-sized assets

---

## 🚀 Quick Start

### For Web Developers

**Using SVG (Recommended):**
```html
<img src="winebox_logo_horizontal.svg" alt="WineBox" width="400" height="120">
```

**Using PNG (if needed):**
```html
<img src="winebox_logo_horizontal_web.png" 
     srcset="winebox_logo_horizontal_web@2x.png 2x" 
     alt="WineBox" 
     width="400" 
     height="120">
```

**CSS:**
```css
.winebox-logo {
  background-image: url('winebox_logo_horizontal.svg');
  background-size: contain;
  background-repeat: no-repeat;
  width: 400px;
  height: 120px;
}
```

### For Generating All Exports

```bash
# Install dependencies
pip install cairosvg pillow

# Generate all logo variants (web, print, social, favicons)
python winebox_export.py --all

# Generate only web assets
python winebox_export.py --format web

# Generate only print assets (300 DPI)
python winebox_export.py --format print

# Specify output directory
python winebox_export.py --all --output ./brand_assets
```

**Output Structure:**
```
exports/
├── web/
│   ├── logo_horizontal_web.png (400×120)
│   ├── logo_horizontal_web@2x.png (800×240)
│   ├── logo_horizontal_web@3x.png (1600×480)
│   ├── icon_web_256.png
│   ├── icon_web_512.png
│   └── icon_web_1024.png
├── print/
│   ├── logo_horizontal_print_300dpi.png (2400×720)
│   ├── logo_horizontal_print_300dpi_large.png (4800×1440)
│   └── icon_print_300dpi_2048.png
├── social/
│   ├── winebox_linkedin_400x400.png
│   ├── winebox_instagram_1080x1080.png
│   ├── winebox_twitter_400x400.png
│   └── winebox_facebook_500x500.png
└── favicons/
    ├── favicon_16.png through favicon_512.png
```

### For Designers & Print Partners

1. **Review BRAND.md** for color codes, typography, and brand voice
2. **Review EXPORT_SPECS.md** for exact specifications for your use case
3. **Download required PNG files** from exports folder (or generate them)
4. Use as templates for your design work

---

## 📋 File Reference

| File | Purpose | Format |
|------|---------|--------|
| `BRAND.md` | **Complete brand guidelines** - colors, fonts, voice, usage rules | Markdown |
| `EXPORT_SPECS.md` | **Detailed export specifications** - sizes, DPI, file names, implementation guides | Markdown |
| `winebox_logo_horizontal.svg` | **Primary logo** - color, full horizontal lockup | SVG |
| `winebox_icon.svg` | **Icon logo** - color, square symbol only | SVG |
| `winebox_logo_monochrome.svg` | **Single-color logo** - for limited-color printing and embroidery | SVG |
| `winebox_export.py` | **Export automation script** - generates all PNG variants | Python 3.7+ |
| `README.md` | This file | Markdown |

---

## 🎨 Brand Overview

**WineBox** is a personal wine cellar collection management app for enthusiasts. The brand combines sophistication with approachability - professional without being stuffy.

### Color Palette

**Primary Colors:**
- **Wine Red** #8B3A3A - Main brand color
- **Deep Wine** #5A1D1D - Accents and text
- **Gold** #D4AF37 - Premium highlights
- **Cream** #FEFEF8 - Backgrounds

[See full palette in BRAND.md]

### Typography

**Serif Font:** Georgia or Garamond  
**Use:** All headings, body text, and logo

[See detailed specs in BRAND.md]

### Brand Voice

Sophisticated yet approachable, knowledgeable but not gatekeeping, elegant but accessible.

**Example:** "Track every bottle with notes on tasting, price, and perfect occasions. Your collection tells your story."

[See full voice and tone guidelines in BRAND.md]

---

## 🖼️ Using the Logo

### Primary Logos

**Horizontal Lockup** (use by default)
- Best for: Headers, navigation, documents
- Minimum size: 180px wide (web), 2 inches (print)
- File: `winebox_logo_horizontal.svg`

**Icon/Symbol** (square format)
- Best for: App icons, favicons, small spaces
- Minimum size: 32px × 32px
- File: `winebox_icon.svg`

**Monochrome** (single color)
- Best for: Embroidery, single-color printing, limited-color media
- File: `winebox_logo_monochrome.svg`

### Clear Space
Maintain clear space around logo equal to the height of the "W". Don't place other elements within this space.

### Don'ts
❌ Don't change colors (unless using monochrome intentionally)  
❌ Don't stretch or distort  
❌ Don't add shadows or effects  
❌ Don't use pixelated/blurry raster versions  
❌ Don't rotate or skew

---

## 📱 Digital & Web Usage

### Favicon Implementation

```html
<link rel="icon" type="image/png" sizes="32x32" href="favicon_32.png">
<link rel="icon" type="image/png" sizes="16x16" href="favicon_16.png">
<link rel="apple-touch-icon" href="favicon_180.png">
```

### PWA Manifest (manifest.json)

```json
{
  "icons": [
    { "src": "favicon_192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "favicon_512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

### Email Signature

Use `logo_horizontal_web.png` at 200px width in an HTML table. See EXPORT_SPECS.md for full template.

---

## 🖨️ Print & Partnerships

### Business Cards
Logo size: 0.75" wide × 0.225" tall  
Use: `logo_horizontal_print_300dpi.png`

### Letterhead
Logo size: 1.5" - 2" wide at top  
Use: `logo_horizontal_print_300dpi.png`

### Brochures & Pamphlets
Cover: 2" - 3" wide  
Interior/footer: 0.75" - 1.5" wide  
Use: `logo_horizontal_print_300dpi.png`

### Posters & Large Prints
Use: `logo_horizontal_print_300dpi_large.png` (4800×1440 @ 300 DPI)  
Scales to 16" × 4.8"

---

## 🌐 Social Media

Pre-sized assets are ready for upload:

| Platform | Filename | Size |
|----------|----------|------|
| **LinkedIn** | `winebox_linkedin_400x400.png` | 400×400px |
| **Instagram** | `winebox_instagram_1080x1080.png` | 1080×1080px |
| **Twitter/X** | `winebox_twitter_400x400.png` | 400×400px |
| **Facebook** | `winebox_facebook_500x500.png` | 500×500px |

Simply upload the PNG file directly to the platform.

---

## 🔧 For Claude Code Development

### Adding to Python/FastAPI Projects

```python
# In your static files or CDN setup
LOGO_PATH = "static/assets/winebox_logo_horizontal.svg"
ICON_PATH = "static/assets/winebox_icon.svg"

# Generate dynamic Open Graph meta tags
def get_og_image_url():
    return f"{SITE_URL}/static/assets/winebox_icon_web_512.png"

# Use in templates
from pathlib import Path
logo_svg = (Path(__file__).parent / "static" / "winebox_logo_horizontal.svg").read_text()
```

### Static File Serving

```python
# FastAPI example
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

# HTML template
<img src="/static/winebox_logo_horizontal.svg" alt="WineBox" width="400">
```

### Building Docker Images with Branding

```dockerfile
FROM python:3.11-slim

COPY winebox_logo_horizontal.svg /app/static/
COPY winebox_icon.svg /app/static/
COPY brand/ /app/brand/

ENV LOGO_PATH=/app/static/winebox_logo_horizontal.svg
```

---

## 📚 Full Documentation

For complete details on any aspect:

- **Brand Guidelines:** See `BRAND.md`
  - Colors with RGB/hex values
  - Complete typography specs
  - Voice and tone guidelines
  - Photography style guide
  - Comprehensive usage rules

- **Export Specifications:** See `EXPORT_SPECS.md`
  - All sizes and DPI requirements
  - File naming conventions
  - Implementation code examples
  - Command-line tools
  - Troubleshooting

---

## 🚨 Quality Notes

The SVG files are vector-based and will scale to any size crisply. When you need PNG files:

1. **For web:** Use the provided PNG exports (web/, 72 DPI)
2. **For print:** Use print/ folder (300 DPI) - these are crisp and production-ready
3. **For social:** Use pre-sized social/ folder assets
4. **For custom sizes:** Use the Python export script or export manually from SVG

**Why are my PNGs blurry?**
- Using old/low-DPI exports
- Scaling PNG files larger than original
- Using compressed/re-exported versions

**Solution:** Regenerate PNG files from SVG at desired size using the export script or SVG software.

---

## 📦 Sharing the Brand Kit

When sharing with partners, designers, or vendors, include:

1. ✅ The SVG files (preferred format)
2. ✅ The BRAND.md file (guidelines)
3. ✅ The EXPORT_SPECS.md file (technical specs)
4. ✅ A subset of the most-needed PNG exports (web + print)
5. ✅ The winebox_export.py script (for custom exports)
6. ✅ A copy of this README

**Do NOT share:** Internal files, design source files, or deprecated assets.

---

## 🤝 Partner & Vendor Guidelines

When working with external partners (printers, agencies, social media managers):

**Provide:**
- BRAND.md and EXPORT_SPECS.md
- SVG files (they can export to their preferred format)
- Specific size/format requirements for their use case
- Color hex codes and fonts

**Restrict:**
- Brand kit to only partners under NDA
- Do not allow partners to modify logo without approval
- Do not allow use outside of agreed-upon scope

**Collect:**
- Final deliverables in multiple formats (if customized)
- Proof/mockups before final production
- Usage rights documentation

---

## 🔐 Brand Asset Management

### Asset Versioning

Current version: **1.0**  
Last updated: **March 30, 2025**

When assets change:
1. Increment version number
2. Update BRAND.md with date
3. Archive old versions (if needed)
4. Notify partners of changes

### Backup & Storage

Store master files in:
- GitHub private repo (version control)
- Cloud storage (Google Drive, Dropbox)
- Local development environment

---

## 🆘 Troubleshooting

### "PNGs are blurry/grainy"

**Cause:** Low resolution or improper export

**Solution:**
```bash
# Regenerate at correct DPI
python winebox_export.py --format web  # For 72 DPI web assets
python winebox_export.py --format print  # For 300 DPI print assets

# Or use ImageMagick
convert -density 300 -resize 2400x720 winebox_logo_horizontal.svg output.png
```

### "Colors don't match"

**Verify hex codes:**
- Wine Red: #8B3A3A
- Deep Wine: #5A1D1D
- Gold: #D4AF37
- Cream: #FEFEF8

Check BRAND.md for official values.

### "Logo looks wrong in my design"

1. Verify you're using an approved logo file (not modified)
2. Check minimum size requirements
3. Ensure adequate clear space around logo
4. Check contrast ratio (text on logo background)
5. Review "What Not to Do" section in BRAND.md

### "Can I use the logo in different colors?"

**Only the monochrome version should be modified** for single-color applications. For other colors, contact branding@winebox.app for approval.

---

## 📞 Support & Contact

**Brand inquiries:** branding@winebox.app  
**Logo updates/corrections:** hello@winebox.app  
**Partnership branding:** partners@winebox.app

---

## 📄 License & Usage Rights

These brand assets are proprietary to WineBox and for authorized use only.

**Internal use:** Unlimited  
**Partner use:** Requires written approval  
**Public sharing:** Not permitted without authorization  

For questions about usage rights, contact branding@winebox.app

---

**Version 1.0**  
**Last Updated: March 30, 2025**  
**Next Review: September 2025**