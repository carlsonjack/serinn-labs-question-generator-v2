"""Normalize spreadsheet column headers to stat_values lookup keys."""

from __future__ import annotations

_PERCENT_SHORT_MAX_LEN = 6


def _token_key(column: str) -> str:
    key = "".join(ch if ch.isalnum() else "_" for ch in column.strip().upper())
    return "_".join(part for part in key.split("_") if part)


def stat_storage_key(column: str) -> str:
    """Normalize a spreadsheet column header to the stat_values lookup key."""

    col = column.strip()
    if "%" in col and len(col) <= _PERCENT_SHORT_MAX_LEN:
        return col.upper()
    return _token_key(col)
