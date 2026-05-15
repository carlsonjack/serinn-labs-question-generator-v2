"""Main upload CSV export (EPIC 7).

Writes validated :class:`OutputRow` records with client schema column order,
UTF-8 with BOM (``utf-8-sig``) so Excel and similar tools open accented text
correctly, and timestamped filenames under ``outputs/``.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.data_layout import bootstrap_if_needed, get_writable_root, uses_writable_data_tree
from core.generation.content import IMPORT_OUTPUT_COLUMNS, ImportQuestionRow
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow
from core.generation.stocks import StockQuestionRow

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_output_dir() -> Path:
    bootstrap_if_needed()
    if uses_writable_data_tree():
        out = get_writable_root() / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        return out
    return _PROJECT_ROOT / "outputs"


DEFAULT_OUTPUT_DIR = _default_output_dir()

# BOM helps Excel/Numbers auto-detect UTF-8; plain utf-8 often mis-reads as Latin-1.
CSV_WRITE_ENCODING = "utf-8-sig"


def sanitize_filename_component(value: str) -> str:
    """Reduce *value* to a filesystem-safe single path segment."""
    s = value.strip()
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


def _format_date_window_segment(start: str, end: str) -> str:
    """Build one ``date_window`` segment for the filename."""
    a = start.strip().replace("/", "-")
    b = end.strip().replace("/", "-")
    return f"{a}_to_{b}"


def _format_timestamp(now: datetime) -> str:
    """Compact, filesystem-safe timestamp including microseconds."""
    return now.strftime("%Y%m%d_%H%M%S_%f")


def build_generated_csv_path(
    subcategory: str,
    date_window_start: str,
    date_window_end: str,
    *,
    output_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Return ``outputs/generated_{subcategory}_{date_window}_{timestamp}.csv``.

    *output_dir* defaults to the project ``outputs/`` directory (not cwd).
    *now* defaults to :func:`datetime.now`; inject for tests.
    """
    base = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    safe_sub = sanitize_filename_component(subcategory)
    date_window = _format_date_window_segment(date_window_start, date_window_end)
    ts = _format_timestamp(now or datetime.now())
    name = f"generated_{safe_sub}_{date_window}_{ts}.csv"
    return base / name


def write_generated_csv(
    rows: Sequence[OutputRow],
    path: str | Path,
) -> Path:
    """Write *rows* to CSV using :data:`OUTPUT_COLUMNS` order; UTF-8, no index column."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())

    logger.info("Wrote %d row(s) to %s", len(rows), out)
    return out


def write_stock_import_csv(
    rows: Sequence[StockQuestionRow],
    path: str | Path,
) -> Path:
    """Write stock MVP rows using the client's titled import columns."""

    return write_import_csv(rows, path)


def write_import_csv(
    rows: Sequence[ImportQuestionRow],
    path: str | Path,
) -> Path:
    """Write deterministic import rows using Jim's titled import columns."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=IMPORT_OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_import_dict())
    logger.info("Wrote %d import row(s) to %s", len(rows), out)
    return out


def write_generated_csv_auto(
    rows: Sequence[OutputRow],
    *,
    subcategory: str,
    date_filter: Mapping[str, Any],
    output_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Build path from *subcategory* and *date_filter* (``start`` / ``end``), then write."""
    start = str(date_filter["start"])
    end = str(date_filter["end"])
    path = build_generated_csv_path(
        subcategory,
        start,
        end,
        output_dir=output_dir,
        now=now,
    )
    return write_generated_csv(rows, path)


def write_stock_import_csv_auto(
    rows: Sequence[StockQuestionRow],
    *,
    date_filter: Mapping[str, Any],
    output_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Build a stock-specific output path and write the client import CSV."""

    start = str(date_filter["start"])
    end = str(date_filter["end"])
    path = build_generated_csv_path(
        "stocks",
        start,
        end,
        output_dir=output_dir,
        now=now,
    )
    return write_stock_import_csv(rows, path)


def write_content_import_csv_auto(
    rows: Sequence[ImportQuestionRow],
    *,
    subcategory: str,
    date_filter: Mapping[str, Any],
    output_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Build a content-specific output path and write the client import CSV."""

    start = str(date_filter["start"])
    end = str(date_filter["end"])
    path = build_generated_csv_path(
        subcategory,
        start,
        end,
        output_dir=output_dir,
        now=now,
    )
    return write_import_csv(rows, path)
