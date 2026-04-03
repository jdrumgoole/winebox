"""Row filtering and data conversion functions for wine imports."""

import re
from datetime import datetime, timezone
from typing import Any

from winebox.db import PyObjectId
from winebox.models.wine import InventoryInfo

from .constants import NON_WINE_KEYWORDS, VALID_WINE_FIELDS

# Pre-compile a single regex that matches any non-wine keyword as a whole word
_NON_WINE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in NON_WINE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_non_wine_row(row: dict[str, Any], mapping: dict[str, str]) -> bool:
    """Check if a row appears to be a non-wine item (spirits, beer, etc.).

    Checks columns mapped to wine_type_id or name for non-wine keywords.
    Uses word-boundary matching to avoid false positives from keywords
    embedded inside wine names (e.g. 'ale' inside 'NeroBufaleffj').

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
        value = row.get(col, "").strip()
        if _NON_WINE_RE.search(value):
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


_DATE_FORMATS = [
    "%Y-%m-%d",       # 2024-03-15
    "%d/%m/%Y",       # 15/03/2024
    "%m/%d/%Y",       # 03/15/2024
    "%d-%m-%Y",       # 15-03-2024
    "%d %b %Y",       # 15 Mar 2024
    "%d %B %Y",       # 15 March 2024
    "%b %d, %Y",      # Mar 15, 2024
    "%B %d, %Y",      # March 15, 2024
    "%Y/%m/%d",       # 2024/03/15
]


def _coerce_date(value: str) -> datetime | None:
    """Try to parse a date string into a timezone-aware datetime."""
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _wine_identity_key(wine_data: dict[str, Any]) -> tuple[str, ...]:
    """Build a dedup identity tuple from wine data.

    Uses (name, winery, vintage) as the key. All values are lowercased
    and stripped for comparison. Missing fields use empty string.
    """
    name = str(wine_data.get("name", "")).strip().lower()
    winery = str(wine_data.get("winery", "") or "").strip().lower()
    vintage = str(wine_data.get("vintage", "") or "").strip()
    return (name, winery, vintage)


def _compute_custom_fields_text(custom_fields: dict[str, str] | None) -> str | None:
    """Compute denormalized text from custom fields for search indexing."""
    if not custom_fields:
        return None
    return " ".join(f"{k} {v}" for k, v in custom_fields.items())


def row_to_wine_data(
    row: dict[str, Any],
    mapping: dict[str, str],
    owner_id: PyObjectId,
    default_quantity: int = 1,
    existing_wines: set[tuple[str, ...]] | None = None,
) -> dict[str, Any] | None:
    """Convert a spreadsheet row to Wine constructor kwargs.

    Args:
        row: Raw row dict from spreadsheet.
        mapping: Column mapping dict.
        owner_id: Owner's ID.
        default_quantity: Default quantity if not specified in row.
        existing_wines: Set of (name, winery, vintage) tuples already in cellar.
            If provided and the wine matches, the returned dict will include
            ``_duplicate: True`` so callers can flag it.

    Returns:
        Dict of Wine constructor kwargs, or None if row has no name.
    """
    wine_data: dict[str, Any] = {}
    custom_fields: dict[str, str] = {}
    quantity = default_quantity
    case_size: int | None = None

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
        elif field == "case_size":
            coerced = _coerce_int(value)
            if coerced is not None and coerced > 0:
                case_size = coerced
        elif field == "purchase_date":
            coerced_date = _coerce_date(value)
            if coerced_date is not None:
                wine_data["purchase_date"] = coerced_date
        elif field in VALID_WINE_FIELDS:
            wine_data[field] = value

    # Compute total bottles from quantity and case_size
    # quantity = number of cases (or loose bottles if no case_size)
    # case_size = bottles per case (e.g. 6, 12)
    # total_bottles = quantity * case_size (if cases) or quantity (if loose)
    num_cases = 0
    if case_size is not None and case_size > 0:
        num_cases = quantity
        total_bottles = quantity * case_size
    else:
        total_bottles = quantity

    # Name is required
    if "name" not in wine_data:
        return None

    wine_data["owner_id"] = owner_id
    wine_data["front_label_text"] = ""
    wine_data["inventory"] = InventoryInfo(
        quantity=total_bottles,
        case_size=case_size if case_size else None,
        updated_at=datetime.now(timezone.utc),
    )
    # Store case info for the processor to create Case records
    wine_data["_num_cases"] = num_cases
    wine_data["_case_size"] = case_size

    if custom_fields:
        wine_data["custom_fields"] = custom_fields
        wine_data["custom_fields_text"] = _compute_custom_fields_text(custom_fields)

    # Flag potential duplicates (not auto-skipped — caller decides)
    if existing_wines is not None:
        key = _wine_identity_key(wine_data)
        if key in existing_wines:
            wine_data["_duplicate"] = True

    return wine_data
