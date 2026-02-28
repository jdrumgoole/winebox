"""Row filtering and data conversion functions for wine imports."""

from datetime import datetime, timezone
from typing import Any

from beanie import PydanticObjectId

from winebox.models.wine import InventoryInfo

from .constants import NON_WINE_KEYWORDS, VALID_WINE_FIELDS


def is_non_wine_row(row: dict[str, Any], mapping: dict[str, str]) -> bool:
    """Check if a row appears to be a non-wine item (spirits, beer, etc.).

    Checks columns mapped to wine_type_id or name for non-wine keywords.

    Args:
        row: Raw row dict from spreadsheet.
        mapping: Column mapping dict.

    Returns:
        True if the row appears to be a non-wine item.
    """
    # Find columns mapped to type or name
    cols_to_check = []
    for header, field in mapping.items():
        if field in ("wine_type_id", "name"):
            cols_to_check.append(header)

    for col in cols_to_check:
        value = row.get(col, "").lower().strip()
        for keyword in NON_WINE_KEYWORDS:
            if keyword in value:
                return True

    return False


def _coerce_vintage(value: str) -> int | None:
    """Try to coerce a string to a vintage year."""
    if not value:
        return None
    try:
        year = int(float(value))
        if 1900 <= year <= 2100:
            return year
    except (ValueError, OverflowError):
        pass
    return None


def _coerce_float(value: str) -> float | None:
    """Try to coerce a string to a float."""
    if not value:
        return None
    # Strip % sign if present
    cleaned = value.replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, OverflowError):
        return None


def _coerce_int(value: str) -> int | None:
    """Try to coerce a string to an int."""
    if not value:
        return None
    try:
        return int(float(value))
    except (ValueError, OverflowError):
        return None


def _compute_custom_fields_text(custom_fields: dict[str, str] | None) -> str | None:
    """Compute denormalized text from custom fields for search indexing."""
    if not custom_fields:
        return None
    return " ".join(f"{k} {v}" for k, v in custom_fields.items())


def row_to_wine_data(
    row: dict[str, Any],
    mapping: dict[str, str],
    owner_id: PydanticObjectId,
    default_quantity: int = 1,
) -> dict[str, Any] | None:
    """Convert a spreadsheet row to Wine constructor kwargs.

    Args:
        row: Raw row dict from spreadsheet.
        mapping: Column mapping dict.
        owner_id: Owner's ID.
        default_quantity: Default quantity if not specified in row.

    Returns:
        Dict of Wine constructor kwargs, or None if row has no name.
    """
    wine_data: dict[str, Any] = {}
    custom_fields: dict[str, str] = {}
    quantity = default_quantity

    for header, field in mapping.items():
        value = row.get(header, "").strip()
        if not value:
            continue

        if field == "skip":
            continue
        elif field.startswith("custom:"):
            custom_field_name = field[7:]  # Remove "custom:" prefix
            custom_fields[custom_field_name] = value
        elif field == "vintage":
            coerced = _coerce_vintage(value)
            if coerced is not None:
                wine_data["vintage"] = coerced
        elif field == "alcohol_percentage":
            coerced = _coerce_float(value)
            if coerced is not None:
                wine_data["alcohol_percentage"] = coerced
        elif field == "quantity":
            coerced = _coerce_int(value)
            if coerced is not None and coerced > 0:
                quantity = coerced
        elif field in VALID_WINE_FIELDS:
            wine_data[field] = value

    # Name is required
    if "name" not in wine_data:
        return None

    wine_data["owner_id"] = owner_id
    wine_data["front_label_text"] = ""
    wine_data["inventory"] = InventoryInfo(
        quantity=quantity,
        updated_at=datetime.now(timezone.utc),
    )

    if custom_fields:
        wine_data["custom_fields"] = custom_fields
        wine_data["custom_fields_text"] = _compute_custom_fields_text(custom_fields)

    return wine_data
