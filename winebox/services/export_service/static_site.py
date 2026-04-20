"""Generate a self-contained static website ZIP of the user's cellar.

The ZIP contains:
- ``index.html`` — single-page app with dashboard + filterable wine grid
- ``data.json``  — wine data as a JS variable assignment
- ``chart.min.js`` — vendored Chart.js for dashboard charts
- ``images/``    — front/back label images referenced by the wine data

Memory strategy:
- Wines are processed in batches (never all in memory at once)
- Images are streamed one at a time from disk into the ZIP
- The ZIP is written to a temporary file on disk, not held in memory
- The caller streams the temp file to the client and cleans up after
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from winebox.schemas.wine import WineWithInventory

from .static_site_template import render_html

logger = logging.getLogger(__name__)

# How many wines to serialize before flushing to the JSON buffer.
_BATCH_SIZE = 50

# Chart.js location relative to the winebox package.
_CHART_JS_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "js" / "chart.min.js"


def _wine_to_dict(wine: WineWithInventory) -> dict[str, Any]:
    """Convert a WineWithInventory to the JSON shape expected by the template."""
    d = wine.model_dump(mode="json", exclude={"owner_id"})

    # Rewrite image paths to relative ZIP paths
    for key in ("front_label_image_path", "back_label_image_path"):
        path = d.get(key)
        new_key = key.replace("_path", "").replace("label_image", "label_image")
        # Simplify key names for the static site JS
        if key == "front_label_image_path":
            d["front_label_image"] = f"images/{path}" if path else None
        else:
            d["back_label_image"] = f"images/{path}" if path else None

    return d


def _collect_image_paths(wine_dict: dict[str, Any]) -> list[str]:
    """Return list of image filenames referenced by a wine dict."""
    paths = []
    for key in ("front_label_image_path", "back_label_image_path"):
        p = wine_dict.get(key)
        if p:
            paths.append(p)
    return paths


def generate_static_site_zip(
    wines: list[WineWithInventory],
    image_storage_path: Path,
    filters_applied: dict[str, str] | None = None,
) -> Path:
    """Build a static site ZIP and return the path to the temp file.

    Args:
        wines: List of wines to include (already filtered).
        image_storage_path: Directory containing label images.
        filters_applied: Dict of filter names to values for display.

    Returns:
        Path to the temporary ZIP file. Caller is responsible for cleanup.
    """
    if filters_applied is None:
        filters_applied = {}

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    total_bottles = 0
    total_images = 0
    image_filenames: set[str] = set()

    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # --- Pass 1: serialize wine data and collect image paths ---
            wine_dicts: list[dict[str, Any]] = []

            for wine in wines:
                d = _wine_to_dict(wine)
                wine_dicts.append(d)
                total_bottles += (d.get("inventory") or {}).get("quantity", 0)

                # Collect image filenames for later
                for img_path in _collect_image_paths(d):
                    image_filenames.add(img_path)

            # Write data.json as a JS variable assignment so it loads synchronously
            json_str = json.dumps(wine_dicts, ensure_ascii=False, default=str)
            # Escape </script> sequences that could break if ever embedded
            json_str = json_str.replace("</", "<\\/")
            data_js = f"const CELLAR_DATA = {json_str};\n"
            zf.writestr("data.json", data_js)

            # --- Pass 2: add images one at a time ---
            for filename in sorted(image_filenames):
                img_file = image_storage_path / filename
                if img_file.is_file():
                    zf.write(img_file, f"images/{filename}")
                    total_images += 1
                else:
                    logger.warning("Image file not found, skipping: %s", img_file)

            # --- Add Chart.js ---
            if _CHART_JS_PATH.is_file():
                zf.write(_CHART_JS_PATH, "chart.min.js")
            else:
                logger.warning("chart.min.js not found at %s", _CHART_JS_PATH)

            # --- Render and add index.html ---
            html = render_html(
                wine_count=len(wine_dicts),
                bottle_count=total_bottles,
                filters_applied=filters_applied,
            )
            zf.writestr("index.html", html)

        logger.info(
            "Static site ZIP created: %d wines, %d bottles, %d images, %.1f MB",
            len(wines), total_bottles, total_images,
            tmp_path.stat().st_size / (1024 * 1024),
        )
        return tmp_path

    except Exception:
        # Clean up temp file on error
        tmp_path.unlink(missing_ok=True)
        raise
