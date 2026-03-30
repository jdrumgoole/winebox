# WineBox Brand Kit - Claude Code Implementation Guide

Quick guide for using WineBox brand assets in Claude Code projects (Python/FastAPI + MongoDB + Beanie).

## 📁 Project Structure

```
winebox-app/
├── src/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── static/
│   │   │   ├── css/
│   │   │   ├── js/
│   │   │   └── assets/
│   │   │       ├── logos/
│   │   │       │   ├── winebox_logo_horizontal.svg
│   │   │       │   ├── winebox_icon.svg
│   │   │       │   └── favicons/
│   │   │       │       ├── favicon_16.png
│   │   │       │       ├── favicon_32.png
│   │   │       │       └── ...
│   │   │       └── og-image_512.png
│   │   └── templates/
│   │       ├── base.html
│   │       ├── layout.html
│   │       └── ...
│   └── brand/
│       ├── BRAND.md
│       ├── EXPORT_SPECS.md
│       └── brand-specs.json
└── docs/
    └── BRANDING.md
```

## 🚀 FastAPI Setup

### 1. Static Files Configuration

```python
# src/app/config.py
from pathlib import Path
from functools import lru_cache

class Settings:
    BASE_DIR = Path(__file__).resolve().parent.parent
    STATIC_DIR = BASE_DIR / "static"
    ASSETS_DIR = STATIC_DIR / "assets"
    
    # Brand asset paths
    LOGO_PATH = ASSETS_DIR / "logos" / "winebox_logo_horizontal.svg"
    ICON_PATH = ASSETS_DIR / "logos" / "winebox_icon.svg"
    OG_IMAGE_PATH = ASSETS_DIR / "og-image_512.png"
    
    # Brand metadata
    BRAND_NAME = "WineBox"
    BRAND_TAGLINE = "Curate Your Collection"
    
    # Colors for dynamic styling
    BRAND_COLORS = {
        "primary": "#8B3A3A",
        "secondary": "#5A1D1D",
        "accent": "#D4AF37",
        "light": "#FEFEF8",
    }
    
    @property
    def APP_URL(self) -> str:
        return "https://winebox.app"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

### 2. Static Files Mounting

```python
# src/app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .config import get_settings

app = FastAPI(
    title="WineBox",
    description="Curate Your Wine Collection"
)

settings = get_settings()

# Mount static files
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")
```

### 3. Template Context with Brand Data

```python
# src/app/templates.py
from fastapi.templating import Jinja2Templates
from pathlib import Path
from .config import get_settings

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

def get_template_context(request, **kwargs):
    """Inject brand data into all templates"""
    context = {
        "request": request,
        "brand": {
            "name": settings.BRAND_NAME,
            "tagline": settings.BRAND_TAGLINE,
            "colors": settings.BRAND_COLORS,
            "assets": {
                "logo": "/static/assets/logos/winebox_logo_horizontal.svg",
                "icon": "/static/assets/logos/winebox_icon.svg",
                "og_image": "/static/assets/og-image_512.png",
            }
        },
        "app_url": settings.APP_URL,
    }
    context.update(kwargs)
    return context
```

### 4. Router with Brand Context

```python
# src/app/routers/pages.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..templates import templates, get_template_context
from ..config import get_settings

router = APIRouter()
settings = get_settings()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    context = get_template_context(request, page_title="Home")
    return templates.TemplateResponse("index.html", context)

@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    context = get_template_context(request, page_title="About WineBox")
    return templates.TemplateResponse("about.html", context)
```

## 🎨 HTML Templates

### Base Template

```html
<!-- src/app/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Brand metadata -->
    <title>{% block title %}{{ brand.name }} - {{ brand.tagline }}{% endblock %}</title>
    <meta name="description" content="{{ brand.tagline }}">
    
    <!-- Open Graph for social sharing -->
    <meta property="og:title" content="{% block og_title %}WineBox{% endblock %}">
    <meta property="og:description" content="{% block og_description %}{{ brand.tagline }}{% endblock %}">
    <meta property="og:image" content="{{ app_url }}{{ brand.assets.og_image }}">
    <meta property="og:url" content="{{ app_url }}{% block og_url %}/{% endblock %}">
    <meta property="og:type" content="website">
    
    <!-- Favicon -->
    <link rel="icon" type="image/png" sizes="32x32" href="/static/assets/logos/favicons/favicon_32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/assets/logos/favicons/favicon_16.png">
    <link rel="apple-touch-icon" href="/static/assets/logos/favicons/favicon_180.png">
    
    <!-- Brand colors as CSS variables -->
    <style>
        :root {
            --color-primary: {{ brand.colors.primary }};
            --color-secondary: {{ brand.colors.secondary }};
            --color-accent: {{ brand.colors.accent }};
            --color-light: {{ brand.colors.light }};
        }
    </style>
    
    <link rel="stylesheet" href="/static/css/style.css">
    {% block extra_head %}{% endblock %}
</head>
<body>
    {% block header %}
    <header class="header">
        <nav class="navbar">
            <div class="navbar-brand">
                <a href="/">
                    <img src="{{ brand.assets.logo }}" 
                         alt="{{ brand.name }}" 
                         class="logo"
                         width="200"
                         height="60">
                </a>
            </div>
            <nav class="navbar-menu">
                <a href="/">Home</a>
                <a href="/features">Features</a>
                <a href="/about">About</a>
                <a href="/contact">Contact</a>
            </nav>
        </nav>
    </header>
    {% endblock %}
    
    <main>
        {% block content %}{% endblock %}
    </main>
    
    {% block footer %}
    <footer class="footer">
        <div class="footer-content">
            <img src="{{ brand.assets.icon }}" 
                 alt="{{ brand.name }}" 
                 class="footer-icon"
                 width="40"
                 height="40">
            <p>&copy; 2025 {{ brand.name }}. {{ brand.tagline }}</p>
        </div>
    </footer>
    {% endblock %}
    
    <script src="/static/js/main.js"></script>
    {% block extra_scripts %}{% endblock %}
</body>
</html>
```

### Index Template

```html
<!-- src/app/templates/index.html -->
{% extends "base.html" %}

{% block title %}{{ brand.name }} - {{ brand.tagline }}{% endblock %}

{% block content %}
<section class="hero">
    <div class="hero-content">
        <img src="{{ brand.assets.logo }}" 
             alt="{{ brand.name }}" 
             srcset="{{ brand.assets.logo }} 1x"
             width="400"
             height="120">
        <h1>{{ brand.tagline }}</h1>
        <p>Organize, track, and celebrate your wine collection with elegance.</p>
        <a href="/app" class="cta-button">Get Started</a>
    </div>
</section>
{% endblock %}
```

## 🎨 CSS Brand Integration

```css
/* src/app/static/css/style.css */

:root {
    --color-primary: #8B3A3A;
    --color-secondary: #5A1D1D;
    --color-accent: #D4AF37;
    --color-light: #FEFEF8;
    --color-text: #333333;
    
    --font-serif: Georgia, Garamond, serif;
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
    font-family: var(--font-serif);
    color: var(--color-text);
    background-color: var(--color-light);
}

h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-serif);
    color: var(--color-primary);
    font-weight: 700;
}

.logo {
    height: auto;
    max-width: 100%;
}

.navbar-brand a {
    text-decoration: none;
    display: flex;
    align-items: center;
}

.cta-button {
    background-color: var(--color-primary);
    color: white;
    padding: 12px 24px;
    border-radius: 4px;
    text-decoration: none;
    font-weight: 700;
    transition: background-color 0.3s;
}

.cta-button:hover {
    background-color: var(--color-secondary);
}

.accent-line {
    height: 2px;
    background: linear-gradient(to right, var(--color-primary), var(--color-accent));
    width: 100%;
}

/* Hero section */
.hero {
    background-color: var(--color-light);
    padding: 80px 20px;
    text-align: center;
}

.hero-content img {
    margin-bottom: 40px;
}

.hero h1 {
    font-size: 48px;
    margin: 20px 0;
    color: var(--color-secondary);
}

/* Responsive */
@media (max-width: 768px) {
    .hero h1 {
        font-size: 32px;
    }
    
    .logo {
        max-width: 80%;
    }
}
```

## 📊 Open Graph & Meta Tags

```python
# src/app/utils/seo.py
from typing import Optional
from ..config import get_settings

class SEOHelper:
    """Helper for generating SEO meta tags"""
    
    def __init__(self):
        self.settings = get_settings()
    
    def get_og_tags(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str] = None,
        type_: str = "website"
    ) -> dict:
        """Generate Open Graph tags for social sharing"""
        if not image:
            image = f"{self.settings.APP_URL}/static/assets/og-image_512.png"
        
        return {
            "og:title": title,
            "og:description": description,
            "og:image": image,
            "og:url": f"{self.settings.APP_URL}{url}",
            "og:type": type_,
            "twitter:card": "summary_large_image",
            "twitter:title": title,
            "twitter:description": description,
            "twitter:image": image,
        }

# Usage in templates
@router.get("/wine/{wine_id}", response_class=HTMLResponse)
async def wine_detail(request: Request, wine_id: str):
    wine = await get_wine(wine_id)
    seo_helper = SEOHelper()
    og_tags = seo_helper.get_og_tags(
        title=f"{wine.name} - WineBox",
        description=f"{wine.vintage} {wine.region}",
        url=f"/wine/{wine_id}",
        image=wine.image_url if wine.image_url else None
    )
    context = get_template_context(request, wine=wine, og_tags=og_tags)
    return templates.TemplateResponse("wine_detail.html", context)
```

## 📱 PWA Configuration

```python
# src/app/routers/manifest.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..config import get_settings

router = APIRouter()
settings = get_settings()

@router.get("/manifest.json")
async def manifest():
    """PWA Manifest with brand colors and icons"""
    return {
        "name": settings.BRAND_NAME,
        "short_name": "WineBox",
        "description": settings.BRAND_TAGLINE,
        "start_url": "/",
        "display": "standalone",
        "background_color": settings.BRAND_COLORS["light"],
        "theme_color": settings.BRAND_COLORS["primary"],
        "icons": [
            {
                "src": "/static/assets/logos/favicons/favicon_192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/assets/logos/favicons/favicon_512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/assets/logos/favicons/favicon_512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable"
            }
        ],
        "screenshots": [
            {
                "src": "/static/assets/og-image_512.png",
                "sizes": "512x512",
                "type": "image/png",
                "form_factor": "narrow"
            }
        ]
    }
```

## 🔧 Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy brand assets
COPY winebox_logo_horizontal.svg /app/src/app/static/assets/logos/
COPY winebox_icon.svg /app/src/app/static/assets/logos/
COPY favicons/ /app/src/app/static/assets/logos/favicons/
COPY og-image_512.png /app/src/app/static/assets/

# Copy source
COPY src/ /app/src/
COPY requirements.txt /app/

# Install dependencies
RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 🧪 Testing Brand Assets

```python
# tests/test_branding.py
import pytest
from pathlib import Path
from src.app.config import Settings
from PIL import Image

def test_logo_files_exist():
    """Verify all required logo files exist"""
    settings = Settings()
    
    assert settings.LOGO_PATH.exists(), "Logo file not found"
    assert settings.ICON_PATH.exists(), "Icon file not found"
    assert settings.OG_IMAGE_PATH.exists(), "OG image not found"

def test_og_image_dimensions():
    """Verify OG image is correct size"""
    settings = Settings()
    img = Image.open(settings.OG_IMAGE_PATH)
    assert img.size == (512, 512), f"OG image should be 512x512, got {img.size}"

def test_brand_colors_format():
    """Verify brand colors are valid hex codes"""
    settings = Settings()
    import re
    hex_pattern = r"^#[0-9A-Fa-f]{6}$"
    
    for color_name, color_value in settings.BRAND_COLORS.items():
        assert re.match(hex_pattern, color_value), f"Invalid hex color: {color_name} = {color_value}"

@pytest.mark.asyncio
async def test_manifest_endpoint(client):
    """Test PWA manifest generation"""
    response = await client.get("/manifest.json")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["name"] == "WineBox"
    assert manifest["theme_color"] == "#8B3A3A"
    assert len(manifest["icons"]) > 0
```

## 📦 Export PNG Assets for Production

Before deploying, generate all PNG exports:

```bash
# Generate web assets
python winebox_export.py --format web --output ./src/app/static/assets/logos

# Copy to static directory
cp exports/web/*.png src/app/static/assets/logos/
cp exports/social/*.png src/app/static/assets/logos/
cp exports/favicons/*.png src/app/static/assets/logos/favicons/
```

## ✅ Deployment Checklist

- [ ] All SVG files are in `static/assets/logos/`
- [ ] All PNG exports are generated and in correct locations
- [ ] Favicon files are present in `favicons/` subdirectory
- [ ] OG image (512×512 PNG) is in static/assets/
- [ ] Brand colors in CSS match BRAND.md hex codes
- [ ] Logo sizing is responsive
- [ ] Open Graph meta tags are correctly configured
- [ ] PWA manifest is served correctly
- [ ] Social media assets are uploaded to platforms
- [ ] BRAND.md is documented in team wiki/docs

## 🚀 Next Steps

1. **Copy brand assets** to your project static directory
2. **Update config.py** with paths to brand assets
3. **Implement templates** using base.html as template
4. **Generate PNG exports** using winebox_export.py
5. **Test** using pytest examples above
6. **Deploy** to Digital Ocean with Docker
7. **Verify** brand consistency across all pages

---

**Last Updated:** March 30, 2025  
**Compatible with:** FastAPI, Jinja2, MongoDB/Beanie, Digital Ocean deployment
