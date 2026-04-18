"""Constants and utilities for export service."""

from datetime import datetime, timezone
from typing import Any

from openpyxl.styles import Alignment, Font, PatternFill

from winebox.schemas.export import ExportFormat

# Wine export headers
WINE_HEADERS = [
    "id",
    "name",
    "winery",
    "vintage",
    "grape_variety",
    "region",
    "country",
    "alcohol_percentage",
    "wine_type",
    "price_tier",
    "quantity",
    "inventory_updated_at",
    "grape_blend_summary",
    "scores_summary",
    "average_score",
    "created_at",
    "updated_at",
]

# Transaction export headers
TRANSACTION_HEADERS = [
    "id",
    "wine_id",
    "wine_name",
    "wine_vintage",
    "wine_winery",
    "transaction_type",
    "quantity",
    "notes",
    "transaction_date",
    "created_at",
]

# X-Wines export headers
XWINES_HEADERS = [
    "id",
    "name",
    "winery",
    "wine_type",
    "country",
    "region",
    "abv",
    "avg_rating",
    "rating_count",
]

# Excel header styling
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="8B1A4A", end_color="8B1A4A", fill_type="solid")
HEADER_ALIGNMENT = Alignment(horizontal="center")


def format_datetime(dt: datetime | None) -> str:
    """Format datetime for export."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_exported_at() -> str:
    """Return the current UTC time as an ISO 8601 string with a Z suffix.

    Produces a form like ``2026-04-17T12:34:56.789012Z`` — ``.isoformat()``
    alone on a timezone-aware datetime emits ``+00:00``, which some
    downstream parsers do not accept.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def generate_filename(export_type: str, export_format: ExportFormat) -> str:
    """Generate a standardized filename for exports.

    Args:
        export_type: Type of export (e.g., "wines", "transactions")
        export_format: Export format

    Returns:
        Filename string
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = export_format.value
    return f"winebox_{export_type}_{timestamp}.{extension}"


def get_content_type(export_format: ExportFormat) -> str:
    """Get the MIME type for an export format.

    Args:
        export_format: Export format

    Returns:
        MIME type string
    """
    content_types = {
        ExportFormat.CSV: "text/csv",
        ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ExportFormat.YAML: "application/x-yaml",
        ExportFormat.JSON: "application/json",
    }
    return content_types[export_format]
