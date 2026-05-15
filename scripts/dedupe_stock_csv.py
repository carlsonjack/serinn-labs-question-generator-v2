#!/usr/bin/env python3
"""Dedupe a stock import CSV (exact duplicate rows) and write a JSON QA report.

Deterministic only — no LLM. Duplicate key:
(Topic Import ID, Question, Answer Options, Expiration Date).

Usage:
    python scripts/dedupe_stock_csv.py path/to/generated_stocks.csv -o path/to/cleaned.csv
    python scripts/dedupe_stock_csv.py path/to/in.csv -o out.csv --report path/to/report.json
    python scripts/dedupe_stock_csv.py path/to/in.csv --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.stock_csv_dedupe import dedupe_stock_csv_dict_rows, dedupe_stock_csv_file
import csv


def _dry_run(inp: Path) -> None:
    with inp.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header")
        rows = [dict(r) for r in reader]
    kept, result = dedupe_stock_csv_dict_rows(rows)
    summary = {
        "input_path": str(inp.resolve()),
        "input_data_rows": result.input_data_rows,
        "would_keep": result.kept_rows,
        "would_remove": result.removed_count,
    }
    print(json.dumps(summary, indent=2))
    if result.removed_count:
        print("\nFirst 10 removals (input row # -> duplicate of row #):")
        for r in result.removed[:10]:
            q = r.question[:72] + "..." if len(r.question) > 72 else r.question
            print(f"  {r.removed_input_row} -> {r.duplicate_of_input_row}  {q}")


def main() -> None:
    p = argparse.ArgumentParser(description="Remove exact duplicate rows from a stock import CSV.")
    p.add_argument("input_csv", type=Path, help="Input CSV (UTF-8, stock column headers)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output cleaned CSV path (required unless --dry-run or --in-place)",
    )
    p.add_argument(
        "--report",
        type=Path,
        help="JSON report path (default: next to --output as <stem>_dedupe_report.json)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts and sample removals; do not write files",
    )
    p.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite input after copying it to --backup (default: <input>_pre_dedupe.csv)",
    )
    p.add_argument(
        "--backup",
        type=Path,
        help="With --in-place, path for backup copy (default: input stem + _pre_dedupe.csv)",
    )
    args = p.parse_args()

    inp = args.input_csv
    if not inp.is_file():
        raise SystemExit(f"Not a file: {inp}")

    if args.dry_run:
        _dry_run(inp)
        return

    if args.in_place:
        backup = args.backup or inp.with_name(inp.stem + "_pre_dedupe.csv")
        shutil.copy2(inp, backup)
        out = inp
        report = args.report or inp.with_name(inp.stem + "_dedupe_report.json")
        result = dedupe_stock_csv_file(inp, out, report_path=report)
        print(f"Backup: {backup}")
        print(f"Wrote deduped CSV in place: {out}")
        print(f"Report: {report}")
        print(
            json.dumps(
                {
                    "input_data_rows": result.input_data_rows,
                    "kept_rows": result.kept_rows,
                    "removed_count": result.removed_count,
                },
                indent=2,
            )
        )
        return

    if args.output is None:
        raise SystemExit("Provide -o/--output, or use --dry-run, or --in-place")

    out = args.output
    report = args.report or out.with_name(out.stem + "_dedupe_report.json")
    result = dedupe_stock_csv_file(inp, out, report_path=report)
    print(
        json.dumps(
            {
                "input_data_rows": result.input_data_rows,
                "kept_rows": result.kept_rows,
                "removed_count": result.removed_count,
                "output": str(out.resolve()),
                "report": str(report.resolve()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
