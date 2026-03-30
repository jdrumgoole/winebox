# WineBox Logo Export Specifications

Complete reference for all logo export formats, sizes, and requirements for different use cases.

## Quick Reference

| Use Case | Format | Size | DPI | Color Mode |
|----------|--------|------|-----|-----------|
| Website Header | PNG | 800×240px | 72 | RGB/Transparent |
| Website Header 2x | PNG | 1600×480px | 72 | RGB/Transparent |
| Favicon | PNG | 32×32, 64×64, 128×128, 256×256 | 72 | RGB/Transparent |
| App Icon iOS | PNG | 180×180, 512×512 | 72 | RGB/Transparent |
| LinkedIn | PNG | 400×400px | 72 | RGB/Transparent |
| Instagram | PNG | 1080×1080px | 72 | RGB/Transparent |
| Print Materials | PNG | 3000×900px | 300 | CMYK or RGB |
| Business Card | PNG/PDF | 1000×300px | 300 | CMYK |
| Poster A3 | PNG | 3300×4659px | 300 | CMYK |

---

## Web Assets (Digital Use)

### Website Logo - Horizontal

**Primary use:** Website header, navigation bar

| Asset | Dimensions | DPI | Format | Transparency | File Name |
|-------|-----------|-----|--------|--------------|-----------|
| 1x (Standard) | 400×120px | 72 | PNG | Yes | `logo_horizontal_web.png` |
| 2x (Retina) | 800×240px | 72 | PNG | Yes | `logo_horizontal_web@2x.png` |
| 3x (High-DPI) | 1600×480px | 72 | PNG | Yes | `logo_horizontal_web@3x.png` |

**Implementation:**
```html
<img src="logo_horizontal_web.png" 
     srcset="logo_horizontal_web@2x.png 2x, 
             logo_horizontal_web@3x.png 3x" 
     alt="WineBox" 
     height="120">
```

**CSS:**
```css
.logo {
  width: 400px;
  height: 120px;
  background-image: url('logo_horizontal_web.png');
  background-size: contain;
  background-repeat: no-repeat;
}

@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
  .logo {
    background-image: url('logo_horizontal_web@2x.png');
  }
}
```

---

### Website Logo - Icon (Square)

**Primary use:** App icon, favicon, small spaces

| Asset | Dimensions | DPI | Format | Transparency | File Name |
|-------|-----------|-----|--------|--------------|-----------|
| 1x | 256×256px | 72 | PNG | Yes | `icon_web_256.png` |
| 2x | 512×512px | 72 | PNG | Yes | `icon_web_512.png` |
| 3x | 1024×1024px | 72 | PNG | Yes | `icon_web_1024.png` |

---

### Favicon

**Primary use:** Browser tab, bookmarks, address bar

| Asset | Dimensions | DPI | Format | Notes |
|-------|-----------|-----|--------|-------|
| 16×16 | 16×16px | 72 | PNG | Ancient browsers, must be pixel-perfect |
| 32×32 | 32×32px | 72 | PNG | Standard favicon size |
| 64×64 | 64×64px | 72 | PNG | macOS touch icon minimum |
| 128×128 | 128×128px | 72 | PNG | iPad home screen |
| 256×256 | 256×256px | 72 | PNG | macOS Safari tab |
| 512×512 | 512×512px | 72 | PNG | PWA splash screen, app manifest |

**Implementation:**
```html
<!-- Favicon -->
<link rel="icon" type="image/png" sizes="32x32" href="favicon_32.png">
<link rel="icon" type="image/png" sizes="16x16" href="favicon_16.png">

<!-- Apple Touch Icon -->
<link rel="apple-touch-icon" href="favicon_180.png">

<!-- Android Chrome -->
<link rel="icon" type="image/png" sizes="512x512" href="favicon_512.png">
<link rel="icon" type="image/png" sizes="256x256" href="favicon_256.png">
```

**PWA Manifest (manifest.json):**
```json
{
  "icons": [
    { "src": "favicon_192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "favicon_512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

---

## Social Media Assets

Each platform has specific requirements. Use the provided PNG files directly.

### LinkedIn

**Header Logo:** 400×400px  
**Use:** LinkedIn Company Profile Picture

| Asset | Dimensions | File Name |
|-------|-----------|-----------|
| Logo | 400×400px | `winebox_linkedin_400x400.png` |

**Upload Settings:**
- Format: PNG (with transparency acceptable)
- Square format required
- Minimum 400×400px recommended

---

### Instagram

**Profile Picture:** 1080×1080px

| Asset | Dimensions | File Name |
|-------|-----------|-----------|
| Logo | 1080×1080px | `winebox_instagram_1080x1080.png` |

**Upload Settings:**
- Format: PNG, JPG, or GIF
- Square format required
- Will be cropped to circle
- Test sizing on actual profile

---

### Twitter/X

**Profile Picture:** 400×400px

| Asset | Dimensions | File Name |
|-------|-----------|-----------|
| Logo | 400×400px | `winebox_twitter_400x400.png` |

**Upload Settings:**
- Format: PNG or JPG
- Square required (auto-cropped to circle)
- Minimum 400×400px

---

### Facebook

**Profile Picture:** 500×500px

| Asset | Dimensions | File Name |
|-------|-----------|-----------|
| Logo | 500×500px | `winebox_facebook_500x500.png` |

**Cover Photo (if using horizontal logo):**
- Dimensions: 820×462px (minimum)
- Safe zone: center 560×315px

---

## Print Assets (High Resolution)

### General Print Settings

**DPI:** 300 (minimum for professional print)  
**Color Mode:** CMYK (for offset printing) or RGB (for digital print)  
**File Format:** PNG or PDF  
**Bleed:** Add 0.125" (3.175mm) around edges if required by printer

---

### Logo - Full Horizontal (Print)

**Primary use:** Letterhead, brochures, documents

| Asset | Dimensions | DPI | Format | Color Mode | File Name |
|-------|-----------|-----|--------|-----------|-----------|
| Standard | 2400×720px | 300 | PNG | RGB | `logo_horizontal_print_300dpi.png` |
| Large | 4800×1440px | 300 | PNG | RGB | `logo_horizontal_print_300dpi_large.png` |

**Conversion to CMYK:**
```python
from PIL import Image
from PIL.ImageCms import createProfile, ImageCmsProfile
import piexif

# Load RGB image
img = Image.open('logo_horizontal_print_300dpi.png')

# Convert RGB to CMYK
img_cmyk = img.convert('CMYK')
img_cmyk.save('logo_horizontal_print_300dpi_cmyk.png')
```

**Printing Specifications:**
- At 300 DPI, 2400×720px = 8" × 2.4"
- At 300 DPI, 4800×1440px = 16" × 4.8"
- Suitable for A4 letterhead (8.5" × 11")

---

### Icon - Print Quality

**Primary use:** Small logos in documents, printed materials

| Asset | Dimensions | DPI | Format | File Name |
|-------|-----------|-----|--------|-----------|
| Print Icon | 2048×2048px | 300 | PNG | `icon_print_300dpi_2048.png` |

**At 300 DPI:** 2048px = 6.83" square

---

### Business Cards

**Standard US Size:** 3.5" × 2"  
**International (ISO/IEC):** 90mm × 50mm

**Logo Specifications:**
- **Physical Size:** 0.75" wide × 0.225" tall (logo)
- **Pixel Size at 300 DPI:** 225×68px (0.75" × 0.225")
- **With Padding:** Use 300×100px file (100 DPI for 1" × 0.33")

**Business Card Export:**

| Asset | Dimensions | DPI | File |
|-------|-----------|-----|------|
| Logo on Card | 1000×600px | 300 | `logo_businesscard_300dpi.png` |

---

### Letterhead

**Standard Letter Size:** 8.5" × 11"  
**Margins:** Top 1", Sides 0.75", Bottom 1"  

**Logo Placement:**
- **Position:** Top left or centered
- **Size:** 1.5" - 2" wide
- **Pixel dimensions at 300 DPI:** 450-600px wide

| Asset | Dimensions | DPI | File |
|-------|-----------|-----|------|
| Letterhead | 2400×720px | 300 | `logo_horizontal_print_300dpi.png` |

---

### Brochure/Pamphlet

**Tri-fold: 8.5" × 11"**  
**Bi-fold: 8.5" × 5.5"**  
**DPI: 300**

**Logo in Brochure:**
- Cover: 2" - 3" wide
- Interior: 1" - 1.5" wide
- Footer: 0.75" - 1" wide

---

### Poster (A3 - 11.7" × 16.5")

**Dimensions at 300 DPI:** 3510 × 4950px

**Logo Placement:**
- Corner: 1.5" - 2" wide
- Header: 2.5" - 3" wide
- Export:** Use `logo_horizontal_print_300dpi_large.png` and scale

---

### Wine Bottle Label

**Typical Wine Label:** 3.5" × 4" (87.6 × 101.6mm)

**Logo Size on Label:**
- **Width:** 0.75" - 1"
- **Position:** Top center or side
- **Export:** Create custom 225×75px at 300 DPI for 0.75" × 0.25"

---

## Email Signature Assets

**Email Client Support:** Outlook, Gmail, Apple Mail, Thunderbird

### Email Signature Specification

| Asset | Dimensions | DPI | Format |
|-------|-----------|-----|--------|
| Logo | 180-200px wide | 72 | PNG |
| Icon | 48-64px square | 72 | PNG |

**Email HTML Template:**
```html
<table cellpadding="0" cellspacing="0" border="0" width="100%">
  <tr>
    <td valign="top" width="200">
      <img src="winebox_logo_horizontal_web.png" 
           alt="WineBox" 
           width="200" 
           height="60" 
           style="display:block; border:none;">
    </td>
  </tr>
  <tr>
    <td height="10"></td>
  </tr>
  <tr>
    <td>
      <p style="font-family: Georgia, serif; font-size: 14px; color: #5A1D1D; margin: 5px 0;">
        Your Name<br>
        <span style="color: #8B3A3A; font-weight: bold;">Founder, WineBox</span><br>
        <span style="color: #999999;">hello@winebox.app</span>
      </p>
    </td>
  </tr>
</table>
```

---

## Monochrome/Single-Color Exports

**Use:** Embroidery, engraving, fax, limited-color printing

| Asset | Dimensions | File |
|-------|-----------|------|
| Web | 800×240px | `logo_monochrome_web@2x.png` |
| Print | 2400×720px @ 300 DPI | `logo_monochrome_print_300dpi.png` |

**Color Options for Monochrome:**
- Black (#000000) on white/light backgrounds
- White on dark backgrounds
- Single spot color (wine red #8B3A3A recommended)

---

## File Naming Convention

```
[asset]_[context]_[size/format].png

Examples:
- logo_horizontal_web.png
- logo_horizontal_web@2x.png
- logo_horizontal_print_300dpi.png
- icon_web_512.png
- icon_print_300dpi_2048.png
- favicon_32.png
- winebox_linkedin_400x400.png
- logo_monochrome_web@2x.png
```

---

## Quality Assurance Checklist

Before distributing logo files:

- [ ] File size is reasonable (web < 50KB, print < 500KB)
- [ ] No visible compression artifacts
- [ ] Colors match brand palette (check hex values)
- [ ] Edges are crisp (no blur/antialiasing issues)
- [ ] Transparency is clean (no gray halos around logo)
- [ ] DPI is correct for intended use
- [ ] File naming follows convention
- [ ] Tested in target applications (browser, email, etc.)
- [ ] Tested at printed size (zoom to 100% in image viewer)

---

## Delivery Package Contents

A complete WineBox brand kit should include:

```
winebox-brand-kit/
├── SVG/
│   ├── winebox_logo_horizontal.svg
│   ├── winebox_icon.svg
│   └── winebox_logo_monochrome.svg
├── exports/
│   ├── web/
│   │   ├── logo_horizontal_web.png
│   │   ├── logo_horizontal_web@2x.png
│   │   ├── logo_horizontal_web@3x.png
│   │   ├── icon_web_256.png
│   │   ├── icon_web_512.png
│   │   └── icon_web_1024.png
│   ├── print/
│   │   ├── logo_horizontal_print_300dpi.png
│   │   ├── logo_horizontal_print_300dpi_large.png
│   │   └── icon_print_300dpi_2048.png
│   ├── social/
│   │   ├── winebox_linkedin_400x400.png
│   │   ├── winebox_instagram_1080x1080.png
│   │   ├── winebox_twitter_400x400.png
│   │   └── winebox_facebook_500x500.png
│   └── favicons/
│       ├── favicon_16.png
│       ├── favicon_32.png
│       ├── favicon_64.png
│       ├── favicon_128.png
│       ├── favicon_256.png
│       └── favicon_512.png
├── BRAND.md (Brand Guidelines)
├── EXPORT_SPECS.md (This file)
├── winebox_export.py (Generation script)
└── README.md
```

---

## Tools for Creating Custom Exports

### Command Line

**Using cairosvg (Python):**
```bash
pip install cairosvg

# Basic export
cairosvg winebox_logo_horizontal.svg -o output.png -w 800

# With DPI for print
cairosvg winebox_logo_horizontal.svg -o output.png -d 300 -w 2400
```

**Using ImageMagick:**
```bash
brew install imagemagick

# From SVG to PNG
convert -density 300 -resize 2400x720 winebox_logo_horizontal.svg logo_print.png

# Convert RGB to CMYK
convert logo_print.png -colorspace CMYK logo_print_cmyk.png
```

**Using Inkscape (GUI):**
1. Open SVG file
2. File → Export As
3. Set format to PNG
4. Set DPI (72 for web, 300 for print)
5. Set dimensions if needed
6. Export

### Online Tools

- **CloudConvert:** cloudconvert.com (supports batch, various formats)
- **Convertio:** convertio.co (browser-based, supports DPI)
- **Zamzar:** zamzar.com (email results, reliable)

### Python Automation

```python
from cairosvg import svg2png
from PIL import Image

# Export at multiple DPIs
for dpi in [72, 150, 300]:
    svg2png(
        url="winebox_logo_horizontal.svg",
        write_to=f"logo_dpi{dpi}.png",
        dpi=(dpi, dpi)
    )

# Batch export
sizes = [400, 800, 1600]
for size in sizes:
    svg2png(
        url="winebox_logo_horizontal.svg",
        write_to=f"logo_{size}w.png",
        output_width=size
    )
```

---

## Color Mode Conversion

### RGB to CMYK (for professional printing)

```python
from PIL import Image

# Load and convert
img_rgb = Image.open('logo_print.png')
img_cmyk = img_rgb.convert('CMYK')
img_cmyk.save('logo_print_cmyk.png')
```

**Color Conversions:**
| Color | RGB | CMYK |
|-------|-----|------|
| Wine Red | #8B3A3A | 0% C, 75% M, 75% Y, 40% K |
| Deep Wine | #5A1D1D | 0% C, 80% M, 80% Y, 65% K |
| Gold | #D4AF37 | 6% C, 20% M, 73% Y, 0% K |
| Cream | #FEFEF8 | 0% C, 0% M, 4% Y, 0% K |

---

## Troubleshooting

**Issue: PNG is blurry/grainy**
- Ensure DPI is correct (72 for web, 300 for print)
- Don't scale PNG files larger than original size
- Regenerate from SVG at desired size
- Check that export tool is respecting dimensions

**Issue: Transparency not working**
- Ensure PNG format selected (not JPG)
- Use "PNG with Alpha" if option available
- Verify background is set to transparent in export

**Issue: Colors look different in print vs. screen**
- Use RGB color mode (most printers convert automatically)
- Specify CMYK conversion if using offset printing
- Test with printer before final production
- Account for paper white point (not pure white)

**Issue: File size too large**
- Reduce PNG bit depth (8-bit vs 32-bit)
- Use PNG compression (most tools default to good settings)
- For social media, consider reducing resolution

---

## Support & Questions

For questions about logo exports or brand asset requests:

**Email:** branding@winebox.app  
**Brand Portal:** (URL TBD)  
**Last Updated:** March 30, 2025