"""File parsing functions for CSV and XLSX imports."""

import csv
import io
from typing import Any

from openpyxl import load_workbook

from .constants import MAX_ROWS


def parse_csv(file_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse CSV file content into headers and rows.

    Uses streaming decode via TextIOWrapper to avoid holding the entire
    decoded text in memory at once. Tries UTF-8 first, falls back to Latin-1.

    Args:
        file_content: Raw CSV file bytes.

    Returns:
        Tuple of (headers, rows) where rows are dicts keyed by header name.

    Raises:
        ValueError: If the CSV is empty or has no headers.
    """
    # Try each encoding with streaming TextIOWrapper (avoids decoding entire
    # file into a string at once — memory stays ~1x file size, not 3x).
    reader = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text_stream = io.TextIOWrapper(io.BytesIO(file_content), encoding=encoding)
            reader = csv.DictReader(text_stream)
            # Force header read to trigger any decode error early
            _ = reader.fieldnames
            break
        except (UnicodeDecodeError, csv.Error):
            reader = None
            continue

    if reader is None or reader.fieldnames is None:
        raise ValueError("CSV file has no headers")

    headers = [h.strip() for h in reader.fieldnames if h and h.strip()]
    if not headers:
        raise ValueError("CSV file has no valid headers")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            break
        # Only include non-empty rows — process one row at a time
        cleaned = {h.strip(): str(v).strip() if v else "" for h, v in row.items() if h and h.strip()}
        if any(v for v in cleaned.values()):
            rows.append(cleaned)

    return headers, rows


def parse_xlsx(file_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse XLSX file content into headers and rows (first sheet only).

    Uses openpyxl read_only mode and iterates rows lazily to avoid loading
    the entire sheet into memory at once.

    Args:
        file_content: Raw XLSX file bytes.

    Returns:
        Tuple of (headers, rows) where rows are dicts keyed by header name.

    Raises:
        ValueError: If the XLSX is empty or has no headers.
    """
    wb = load_workbook(filename=io.BytesIO(file_content), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        raise ValueError("XLSX file has no worksheets")

    # Iterate rows lazily — don't call list() on the whole sheet
    row_iter = ws.iter_rows(values_only=True)

    # First row = headers
    try:
        raw_headers = next(row_iter)
    except StopIteration:
        wb.close()
        raise ValueError("XLSX file is empty")

    headers = [str(h).strip() if h is not None else "" for h in raw_headers]
    headers = [h for h in headers if h]
    if not headers:
        wb.close()
        raise ValueError("XLSX file has no valid headers")

    rows: list[dict[str, Any]] = []
    for i, row_values in enumerate(row_iter):
        if i >= MAX_ROWS:
            break
        row_dict: dict[str, Any] = {}
        for j, header in enumerate(headers):
            val = row_values[j] if j < len(row_values) else None
            row_dict[header] = str(val).strip() if val is not None else ""
        if any(v for v in row_dict.values()):
            rows.append(row_dict)

    wb.close()
    return headers, rows
