"""Tests for the static website export service."""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from winebox.schemas.wine import CaseBreakdown, InventoryInfo, WineWithInventory
from winebox.services.export_service.static_site import generate_static_site_zip


def _make_wine(
    *,
    wine_id: str = "aaa111",
    name: str = "Test Cabernet",
    winery: str = "Test Winery",
    vintage: int = 2020,
    country: str = "France",
    region: str = "Bordeaux",
    wine_type: str = "red",
    quantity: int = 6,
    front_image: str | None = None,
    back_image: str | None = None,
    enriched_fields: list[str] | None = None,
    grape_variety: str | None = "Cabernet Sauvignon",
    price_tier: str | None = "premium",
    custom_fields: dict[str, str] | None = None,
    cases: list[dict] | None = None,
    loose_bottles: int = 0,
) -> WineWithInventory:
    """Build a WineWithInventory for testing."""
    now = datetime.now(timezone.utc)
    case_list = []
    if cases:
        for c in cases:
            case_list.append(CaseBreakdown(
                cellar_item_id=c.get("id", "case1"),
                case_size=c.get("case_size", 6),
                bottles_remaining=c.get("bottles_remaining", 6),
                provenance=c.get("provenance"),
                purchase_price=c.get("purchase_price"),
            ))

    return WineWithInventory(
        id=wine_id,
        name=name,
        winery=winery,
        vintage=vintage,
        country=country,
        region=region,
        wine_type=wine_type,
        grape_variety=grape_variety,
        price_tier=price_tier,
        enriched_fields=enriched_fields or [],
        custom_fields=custom_fields,
        front_label_text="",
        back_label_text=None,
        front_label_image_path=front_image,
        back_label_image_path=back_image,
        created_at=now,
        updated_at=now,
        inventory=InventoryInfo(
            quantity=quantity,
            cases=case_list,
            loose_bottles=loose_bottles,
            updated_at=now,
        ),
    )


# Minimal valid PNG for test images
_SAMPLE_PNG = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    0x00, 0x00, 0x00, 0x0D,
    0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00,
    0x90, 0x77, 0x53, 0xDE,
    0x00, 0x00, 0x00, 0x0C,
    0x49, 0x44, 0x41, 0x54,
    0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00,
    0x05, 0xFE, 0x02, 0xFE,
    0xA3, 0x1A, 0x8D, 0xEB,
    0x00, 0x00, 0x00, 0x00,
    0x49, 0x45, 0x4E, 0x44,
    0xAE, 0x42, 0x60, 0x82,
])


class TestStaticSiteZip:
    """Tests for the ZIP generation service."""

    def test_produces_valid_zip(self) -> None:
        """A basic export produces a valid ZIP with required files."""
        wines = [_make_wine()]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                assert path.exists()
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
                    assert "index.html" in names
                    assert "data.json" in names
                    assert "cellar.csv" in names
            finally:
                path.unlink(missing_ok=True)

    def test_csv_contains_wine_data(self) -> None:
        """The cellar.csv contains all wines with correct headers."""
        wines = [
            _make_wine(wine_id="w1", name="Wine One", country="France", quantity=6),
            _make_wine(wine_id="w2", name="Wine Two", country="Italy", quantity=3),
        ]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    csv_content = zf.read("cellar.csv").decode("utf-8")
                    import csv as csv_mod
                    reader = csv_mod.DictReader(csv_content.splitlines())
                    rows = list(reader)
                    assert len(rows) == 2
                    assert rows[0]["name"] == "Wine One"
                    assert rows[0]["country"] == "France"
                    assert rows[0]["quantity"] == "6"
                    assert rows[1]["name"] == "Wine Two"
                    assert "wine_type" in reader.fieldnames
                    assert "vintage" in reader.fieldnames
            finally:
                path.unlink(missing_ok=True)

    def test_embedded_json_has_all_fields(self) -> None:
        """The data.json contains all expected augmented fields."""
        wines = [_make_wine(
            custom_fields={"notes": "Excellent vintage"},
            enriched_fields=["country", "region"],
            cases=[{"case_size": 6, "bottles_remaining": 6, "provenance": "Berry Bros"}],
        )]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    data_js = zf.read("data.json").decode("utf-8")
                    # Strip the JS variable assignment wrapper
                    assert data_js.startswith("const CELLAR_DATA = ")
                    json_str = data_js[len("const CELLAR_DATA = "):-2]  # remove trailing ;\n
                    data = json.loads(json_str)

                assert len(data) == 1
                w = data[0]
                assert w["name"] == "Test Cabernet"
                assert w["country"] == "France"
                assert w["wine_type"] == "red"
                assert w["price_tier"] == "premium"
                assert "country" in w["enriched_fields"]
                assert w["custom_fields"]["notes"] == "Excellent vintage"
                assert w["inventory"]["cases"][0]["provenance"] == "Berry Bros"
            finally:
                path.unlink(missing_ok=True)

    def test_images_included_when_present(self) -> None:
        """Image files are added to the ZIP when they exist on disk."""
        wines = [_make_wine(front_image="test-front.png", back_image="test-back.png")]
        with tempfile.TemporaryDirectory() as img_dir:
            (Path(img_dir) / "test-front.png").write_bytes(_SAMPLE_PNG)
            (Path(img_dir) / "test-back.png").write_bytes(_SAMPLE_PNG)

            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
                    assert "images/test-front.png" in names
                    assert "images/test-back.png" in names
                    # Verify the image data is correct
                    assert zf.read("images/test-front.png") == _SAMPLE_PNG
            finally:
                path.unlink(missing_ok=True)

    def test_missing_images_skipped_gracefully(self) -> None:
        """Missing image files don't crash the export."""
        wines = [_make_wine(front_image="nonexistent.png")]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
                    assert "images/nonexistent.png" not in names
                    # data.json should still reference the path
                    data_js = zf.read("data.json").decode("utf-8")
                    assert "nonexistent.png" in data_js
            finally:
                path.unlink(missing_ok=True)

    def test_empty_cellar_produces_valid_zip(self) -> None:
        """An empty cellar produces a valid ZIP with zero wines."""
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip([], Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    assert "index.html" in zf.namelist()
                    assert "data.json" in zf.namelist()
                    data_js = zf.read("data.json").decode("utf-8")
                    json_str = data_js[len("const CELLAR_DATA = "):-2]
                    assert json.loads(json_str) == []

                    html = zf.read("index.html").decode("utf-8")
                    assert "0 wines" in html
            finally:
                path.unlink(missing_ok=True)

    def test_filter_metadata_in_html(self) -> None:
        """Applied filters are shown in the exported HTML header."""
        wines = [_make_wine()]
        filters = {"wine_type": "red", "country": "France"}
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir), filters_applied=filters)
            try:
                with zipfile.ZipFile(path) as zf:
                    html = zf.read("index.html").decode("utf-8")
                    assert "wine_type: red" in html
                    assert "country: France" in html
            finally:
                path.unlink(missing_ok=True)

    def test_multiple_wines(self) -> None:
        """Multiple wines are all present in the export."""
        wines = [
            _make_wine(wine_id="w1", name="Wine One", country="France"),
            _make_wine(wine_id="w2", name="Wine Two", country="Italy"),
            _make_wine(wine_id="w3", name="Wine Three", country="Spain"),
        ]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    data_js = zf.read("data.json").decode("utf-8")
                    json_str = data_js[len("const CELLAR_DATA = "):-2]
                    data = json.loads(json_str)
                    assert len(data) == 3
                    names = {w["name"] for w in data}
                    assert names == {"Wine One", "Wine Two", "Wine Three"}

                    html = zf.read("index.html").decode("utf-8")
                    assert "3 wines" in html
            finally:
                path.unlink(missing_ok=True)

    def test_xss_prevention(self) -> None:
        """Script tags in wine data are escaped in the JSON output."""
        wines = [_make_wine(name='<script>alert("xss")</script>')]
        with tempfile.TemporaryDirectory() as img_dir:
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    data_js = zf.read("data.json").decode("utf-8")
                    # </script> should be escaped
                    assert "</script>" not in data_js
                    assert "<\\/script>" in data_js
            finally:
                path.unlink(missing_ok=True)

    def test_image_paths_rewritten(self) -> None:
        """Image paths in data.json point to images/ directory."""
        wines = [_make_wine(front_image="abc123.jpg")]
        with tempfile.TemporaryDirectory() as img_dir:
            (Path(img_dir) / "abc123.jpg").write_bytes(_SAMPLE_PNG)
            path = generate_static_site_zip(wines, Path(img_dir))
            try:
                with zipfile.ZipFile(path) as zf:
                    data_js = zf.read("data.json").decode("utf-8")
                    json_str = data_js[len("const CELLAR_DATA = "):-2]
                    data = json.loads(json_str)
                    assert data[0]["front_label_image"] == "images/abc123.jpg"
            finally:
                path.unlink(missing_ok=True)
