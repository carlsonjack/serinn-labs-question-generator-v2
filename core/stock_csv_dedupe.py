"""Deterministic duplicate detection for stock import CSVs.

Exact duplicates are keyed by ``(Topic Import ID, Question, Answer Options,
Expiration Date)`` so repeated monthly/daily blocks can be collapsed to a
single row. This is rule-based only — no LLM.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.csv_export import CSV_WRITE_ENCODING
from core.generation.stocks import STOCK_OUTPUT_COLUMNS


@dataclass(frozen=True)
class RemovedDuplicate:
    """One removed row, keyed to the first kept row."""

    removed_input_row: int  # 1-based data row in the input file (excluding header)
    duplicate_of_input_row: int  # 1-based data row of the first kept occurrence
    topic_import_id: str
    question: str
    answer_options: str
    expiration_date: str


@dataclass(frozen=True)
class StockCsvDedupeResult:
    input_path: str
    input_data_rows: int
    kept_rows: int
    removed_count: int
    removed: tuple[RemovedDuplicate, ...]


def stock_csv_duplicate_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Key for exact duplicate detection."""

    return (
        str(row.get("Topic Import ID", "")).strip(),
        str(row.get("Question", "")).strip(),
        str(row.get("Answer Options", "")).strip(),
        str(row.get("Expiration Date", "")).strip(),
    )


def dedupe_stock_csv_dict_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], StockCsvDedupeResult]:
    """Return kept rows in order and a structured report of removals."""

    seen: dict[tuple[str, str, str, str], int] = {}
    kept: list[dict[str, Any]] = []
    removed_list: list[RemovedDuplicate] = []

    for i, row in enumerate(rows, start=1):
        key = stock_csv_duplicate_key(row)
        if key in seen:
            first = seen[key]
            removed_list.append(
                RemovedDuplicate(
                    removed_input_row=i,
                    duplicate_of_input_row=first,
                    topic_import_id=key[0],
                    question=key[1],
                    answer_options=key[2],
                    expiration_date=key[3],
                )
            )
            continue
        seen[key] = i
        kept.append(dict(row))

    result = StockCsvDedupeResult(
        input_path="",
        input_data_rows=len(rows),
        kept_rows=len(kept),
        removed_count=len(removed_list),
        removed=tuple(removed_list),
    )
    return kept, result


def dedupe_stock_csv_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    report_path: str | Path | None = None,
) -> StockCsvDedupeResult:
    """Read *input_path*, write deduped CSV to *output_path*, optional JSON report."""

    inp = Path(input_path)
    out = Path(output_path)
    rows = _read_stock_csv(inp)
    kept, partial = dedupe_stock_csv_dict_rows(rows)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=STOCK_OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in kept:
            writer.writerow({k: row.get(k, "") for k in STOCK_OUTPUT_COLUMNS})

    result = StockCsvDedupeResult(
        input_path=str(inp.resolve()),
        input_data_rows=partial.input_data_rows,
        kept_rows=partial.kept_rows,
        removed_count=partial.removed_count,
        removed=partial.removed,
    )

    report_obj: dict[str, Any] = {
        "input_path": result.input_path,
        "output_path": str(out.resolve()),
        "input_data_rows": result.input_data_rows,
        "kept_rows": result.kept_rows,
        "removed_count": result.removed_count,
        "removed": [asdict(r) for r in result.removed],
    }

    if report_path is not None:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report_obj, indent=2) + "\n", encoding="utf-8")

    return result


def _read_stock_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        missing = [c for c in STOCK_OUTPUT_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                f"CSV missing expected column(s) {missing!r}. "
                f"Found: {list(fieldnames)}. Expected stock import columns."
            )
        return [dict(r) for r in reader]
