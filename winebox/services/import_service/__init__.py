"""Import service package for parsing spreadsheets and creating wine records."""

from .constants import (
    CANONICAL_WINE_FIELDS,
    HEADER_ALIASES,
    MAX_ROWS,
    MIN_CANONICAL_MATCHES,
    NON_WINE_KEYWORDS,
    UPLOAD_CHUNK_SIZE,
    VALID_WINE_FIELDS,
    WINE_FIELD_DESCRIPTIONS,
)
from .converters import (
    _coerce_date,
    _coerce_float,
    _coerce_int,
    _coerce_vintage,
    _compute_custom_fields_text,
    _wine_identity_key,
    is_non_wine_row,
    row_to_wine_data,
)
from .mapping import (
    _is_valid_mapping_value,
    _static_fallback,
    assess_mapping_confidence,
    suggest_column_mapping,
    suggest_column_mapping_ai,
)
from .parsers import parse_csv, parse_xlsx
from .processor import process_import_batch, process_import_batch_streaming
from .utils import chunked

__all__ = [
    # Constants
    "CANONICAL_WINE_FIELDS",
    "HEADER_ALIASES",
    "MAX_ROWS",
    "MIN_CANONICAL_MATCHES",
    "NON_WINE_KEYWORDS",
    "UPLOAD_CHUNK_SIZE",
    "VALID_WINE_FIELDS",
    "WINE_FIELD_DESCRIPTIONS",
    # Parsers
    "parse_csv",
    "parse_xlsx",
    # Mapping
    "assess_mapping_confidence",
    "suggest_column_mapping",
    "suggest_column_mapping_ai",
    "_is_valid_mapping_value",
    "_static_fallback",
    # Converters
    "is_non_wine_row",
    "row_to_wine_data",
    "_coerce_date",
    "_coerce_float",
    "_coerce_int",
    "_coerce_vintage",
    "_compute_custom_fields_text",
    "_wine_identity_key",
    # Processor
    "process_import_batch",
    "process_import_batch_streaming",
    # Utils
    "chunked",
]
