"""Import service package for parsing spreadsheets and creating wine records."""

from .constants import (
    CANONICAL_WINE_FIELDS,
    HEADER_ALIASES,
    MAX_ROWS,
    NON_WINE_KEYWORDS,
    VALID_WINE_FIELDS,
    WINE_FIELD_DESCRIPTIONS,
)
from .converters import (
    _coerce_float,
    _coerce_int,
    _coerce_vintage,
    _compute_custom_fields_text,
    is_non_wine_row,
    row_to_wine_data,
)
from .mapping import (
    _is_valid_mapping_value,
    _static_fallback,
    suggest_column_mapping,
    suggest_column_mapping_ai,
)
from .parsers import parse_csv, parse_xlsx
from .processor import process_import_batch

__all__ = [
    # Constants
    "CANONICAL_WINE_FIELDS",
    "HEADER_ALIASES",
    "MAX_ROWS",
    "NON_WINE_KEYWORDS",
    "VALID_WINE_FIELDS",
    "WINE_FIELD_DESCRIPTIONS",
    # Parsers
    "parse_csv",
    "parse_xlsx",
    # Mapping
    "suggest_column_mapping",
    "suggest_column_mapping_ai",
    "_is_valid_mapping_value",
    "_static_fallback",
    # Converters
    "is_non_wine_row",
    "row_to_wine_data",
    "_coerce_float",
    "_coerce_int",
    "_coerce_vintage",
    "_compute_custom_fields_text",
    # Processor
    "process_import_batch",
]
