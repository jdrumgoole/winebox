#!/usr/bin/env python3
"""
WineBox Logo Export Utility
Generates high-quality PNG exports from SVG logo files at various resolutions
for web, print, social media, and other uses.

Usage:
    python winebox_export.py [--all] [--format web|print|social|icon] [--size SIZE]

Requirements:
    pip install cairosvg pillow

Author: WineBox Brand Team
"""

import os
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple

try:
    from cairosvg import svg2png
except ImportError:
    print("ERROR: cairosvg not installed. Install with: pip install cairosvg")
    sys.exit(1)

from PIL import Image
import io


@dataclass
class ExportConfig:
    """Configuration for logo export"""
    name: str
    svg_file: str
    output_dir: str = "./exports"
    dpi: int = 72
    bg_color: str = "white"  # or "transparent"


class WineBoxExporter:
    """Handles WineBox logo exports at various sizes and formats"""
    
    # Export specifications by type
    EXPORT_SPECS = {
        "web": {
            "logo_horizontal": [
                {"width": 400, "height": 120, "name": "logo_horizontal_web.png"},
                {"width": 800, "height": 240, "name": "logo_horizontal_web@2x.png"},
                {"width": 1600, "height": 480, "name": "logo_horizontal_web@3x.png"},
            ],
            "icon": [
                {"size": 256, "name": "icon_web_256.png"},
                {"size": 512, "name": "icon_web_512.png"},
                {"size": 1024, "name": "icon_web_1024.png"},
            ]
        },
        "print": {
            "logo_horizontal": [
                {"width": 2400, "height": 720, "dpi": 300, "name": "logo_horizontal_print_300dpi.png"},
                {"width": 4800, "height": 1440, "dpi": 300, "name": "logo_horizontal_print_300dpi_large.png"},
            ],
            "icon": [
                {"size": 2048, "dpi": 300, "name": "icon_print_300dpi_2048.png"},
            ]
        },
        "social": {
            "linkedin": {
                "file": "icon",
                "sizes": [{"size": 400, "name": "winebox_linkedin_400x400.png"}],
            },
            "instagram": {
                "file": "icon",
                "sizes": [{"size": 1080, "name": "winebox_instagram_1080x1080.png"}],
            },
            "twitter": {
                "file": "icon",
                "sizes": [{"size": 400, "name": "winebox_twitter_400x400.png"}],
            },
            "facebook": {
                "file": "icon",
                "sizes": [{"size": 500, "name": "winebox_facebook_500x500.png"}],
            }
        },
        "favicon": {
            "icon": [
                {"size": 16, "name": "favicon_16.png"},
                {"size": 32, "name": "favicon_32.png"},
                {"size": 64, "name": "favicon_64.png"},
                {"size": 128, "name": "favicon_128.png"},
                {"size": 256, "name": "favicon_256.png"},
                {"size": 512, "name": "favicon_512.png"},
            ]
        }
    }
    
    def __init__(self, base_dir: str = "."):
        """Initialize exporter with base directory for SVG files"""
        self.base_dir = Path(base_dir)
        self.svgs = {
            "logo_horizontal": self.base_dir / "winebox_logo_horizontal.svg",
            "icon": self.base_dir / "winebox_icon.svg",
            "monochrome": self.base_dir / "winebox_logo_monochrome.svg",
        }
    
    def export_svg_to_png(
        self,
        svg_path: Path,
        output_path: Path,
        width: int = None,
        height: int = None,
        dpi: int = 72,
        bg_color: str = "transparent"
    ) -> bool:
        """
        Convert SVG to PNG with specified dimensions and DPI
        
        Args:
            svg_path: Path to SVG file
            output_path: Path for output PNG
            width: Output width in pixels
            height: Output height in pixels
            dpi: DPI for rendering (default 72 for web, 300 for print)
            bg_color: Background color ("transparent" or color name/hex)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert DPI to scale factor (cairosvg uses DPI internally)
            # Standard is 96 DPI in web context
            scale = dpi / 96.0
            
            # If width and height provided, use them
            if width and height:
                svg2png(
                    url=str(svg_path),
                    write_to=str(output_path),
                    output_width=width,
                    output_height=height,
                )
            else:
                # Fallback: use DPI scaling
                svg2png(
                    url=str(svg_path),
                    write_to=str(output_path),
                    dpi=(dpi, dpi)
                )
            
            # Ensure background color if needed
            if bg_color != "transparent":
                img = Image.open(output_path)
                if img.mode == 'RGBA':
                    # Add background color
                    background = Image.new('RGB', img.size, bg_color)
                    background.paste(img, mask=img.split()[3])
                    background.save(output_path, 'PNG')
            
            file_size_kb = output_path.stat().st_size / 1024
            print(f"✓ {output_path.name:40s} ({file_size_kb:7.1f} KB)")
            return True
            
        except Exception as e:
            print(f"✗ Error exporting {output_path.name}: {e}")
            return False
    
    def export_all(self, output_base: str = "./exports") -> None:
        """Export all logo variations"""
        output_base = Path(output_base)
        
        print("\n🍷 WineBox Logo Export Utility\n")
        print("=" * 60)
        
        # Web exports
        print("\n📱 Web Exports (72 DPI)")
        print("-" * 60)
        for spec in self.EXPORT_SPECS["web"]["logo_horizontal"]:
            self.export_svg_to_png(
                self.svgs["logo_horizontal"],
                output_base / "web" / spec["name"],
                width=spec["width"],
                height=spec["height"],
                dpi=72
            )
        
        for spec in self.EXPORT_SPECS["web"]["icon"]:
            self.export_svg_to_png(
                self.svgs["icon"],
                output_base / "web" / spec["name"],
                width=spec["size"],
                height=spec["size"],
                dpi=72
            )
        
        # Print exports
        print("\n🖨️  Print Exports (300 DPI)")
        print("-" * 60)
        for spec in self.EXPORT_SPECS["print"]["logo_horizontal"]:
            self.export_svg_to_png(
                self.svgs["logo_horizontal"],
                output_base / "print" / spec["name"],
                width=spec["width"],
                height=spec["height"],
                dpi=spec.get("dpi", 300)
            )
        
        for spec in self.EXPORT_SPECS["print"]["icon"]:
            self.export_svg_to_png(
                self.svgs["icon"],
                output_base / "print" / spec["name"],
                width=spec["size"],
                height=spec["size"],
                dpi=spec.get("dpi", 300)
            )
        
        # Social media exports
        print("\n📱 Social Media Exports (72 DPI)")
        print("-" * 60)
        for platform, config in self.EXPORT_SPECS["social"].items():
            svg_file = config["file"]
            for spec in config["sizes"]:
                self.export_svg_to_png(
                    self.svgs[svg_file],
                    output_base / "social" / spec["name"],
                    width=spec["size"],
                    height=spec["size"],
                    dpi=72
                )
        
        # Favicon exports
        print("\n🔗 Favicon Exports (72 DPI)")
        print("-" * 60)
        for spec in self.EXPORT_SPECS["favicon"]["icon"]:
            self.export_svg_to_png(
                self.svgs["icon"],
                output_base / "favicons" / spec["name"],
                width=spec["size"],
                height=spec["size"],
                dpi=72
            )
        
        print("\n" + "=" * 60)
        print(f"✅ All exports completed to: {output_base}/")
        print("=" * 60)
        
        # Print summary
        self._print_summary(output_base)
    
    def _print_summary(self, output_base: Path) -> None:
        """Print summary of generated files"""
        
        stats = {
            "total_files": 0,
            "total_size_kb": 0,
            "by_type": {}
        }
        
        for export_type in ["web", "print", "social", "favicons"]:
            type_dir = output_base / export_type
            if type_dir.exists():
                files = list(type_dir.glob("*.png"))
                size = sum(f.stat().st_size for f in files) / 1024
                count = len(files)
                stats["total_files"] += count
                stats["total_size_kb"] += size
                stats["by_type"][export_type] = (count, size)
        
        print("\n📊 Export Summary:")
        print(f"   Total Files: {stats['total_files']}")
        print(f"   Total Size: {stats['total_size_kb']:.1f} KB")
        print("\n   Breakdown:")
        for export_type, (count, size) in stats["by_type"].items():
            print(f"   - {export_type:15s}: {count:2d} files ({size:7.1f} KB)")
    
    def export_format(self, format_type: str, output_base: str = "./exports") -> None:
        """Export specific format"""
        output_base = Path(output_base)
        
        if format_type == "web":
            print("Exporting web assets...")
            for spec in self.EXPORT_SPECS["web"]["logo_horizontal"]:
                self.export_svg_to_png(
                    self.svgs["logo_horizontal"],
                    output_base / "web" / spec["name"],
                    width=spec["width"],
                    height=spec["height"]
                )
        elif format_type == "print":
            print("Exporting print assets (300 DPI)...")
            for spec in self.EXPORT_SPECS["print"]["logo_horizontal"]:
                self.export_svg_to_png(
                    self.svgs["logo_horizontal"],
                    output_base / "print" / spec["name"],
                    width=spec["width"],
                    height=spec["height"],
                    dpi=300
                )
        elif format_type == "social":
            print("Exporting social media assets...")
            for platform, config in self.EXPORT_SPECS["social"].items():
                svg_file = config["file"]
                for spec in config["sizes"]:
                    self.export_svg_to_png(
                        self.svgs[svg_file],
                        output_base / "social" / spec["name"],
                        width=spec["size"],
                        height=spec["size"]
                    )
        else:
            print(f"Unknown format: {format_type}")


def main():
    """CLI interface"""
    parser = argparse.ArgumentParser(
        description="Generate WineBox logo exports at various resolutions"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all formats (web, print, social, favicon)"
    )
    parser.add_argument(
        "--format",
        choices=["web", "print", "social", "favicon"],
        help="Export specific format"
    )
    parser.add_argument(
        "--output",
        default="./exports",
        help="Output directory (default: ./exports)"
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base directory containing SVG files (default: current directory)"
    )
    
    args = parser.parse_args()
    
    exporter = WineBoxExporter(base_dir=args.base_dir)
    
    if args.all or not args.format:
        exporter.export_all(output_base=args.output)
    else:
        exporter.export_format(args.format, output_base=args.output)


if __name__ == "__main__":
    main()
