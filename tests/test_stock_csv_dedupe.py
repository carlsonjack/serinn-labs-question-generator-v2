"""Tests for stock CSV deduplication."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.generation.stocks import STOCK_OUTPUT_COLUMNS
from core.stock_csv_dedupe import dedupe_stock_csv_dict_rows, dedupe_stock_csv_file, stock_csv_duplicate_key


def _row(**kwargs: str) -> dict[str, str]:
    base = {
        "Topic Import ID": "stocks-us-market",
        "Question": "Q1",
        "Answer Type": "yes_no",
        "Answer Options": "",
        "Start Date": "2026-06-01",
        "Expiration Date": "2026-06-10",
        "Resolution Date": "2026-07-01",
        "Priority": "1",
    }
    base.update(kwargs)
    return base


def test_stock_csv_duplicate_key_strips_whitespace() -> None:
    r = _row(Question="  hi  ", **{"Answer Options": " a ||b "})
    assert stock_csv_duplicate_key(r) == ("stocks-us-market", "hi", "a ||b", "2026-06-10")


def test_dedupe_keeps_first_occurrence_in_order() -> None:
    a = _row(Question="Same", **{"Answer Options": "X||Y"})
    b = _row(Question="Other")
    c = _row(Question="Same", **{"Answer Options": "X||Y"})
    kept, result = dedupe_stock_csv_dict_rows([a, b, c])
    assert [r["Question"] for r in kept] == ["Same", "Other"]
    assert result.removed_count == 1
    assert result.removed[0].removed_input_row == 3
    assert result.removed[0].duplicate_of_input_row == 1


def test_dedupe_stock_csv_file_roundtrip(tmp_path: Path) -> None:
    inp = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    rep = tmp_path / "report.json"
    r1 = _row(Question="Dup")
    r2 = _row(Question="Dup")
    r3 = _row(Question="Unique")
    with inp.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        w = csv.DictWriter(fh, fieldnames=STOCK_OUTPUT_COLUMNS)
        w.writeheader()
        for r in (r1, r2, r3):
            w.writerow(r)

    result = dedupe_stock_csv_file(inp, out, report_path=rep)

    assert result.input_data_rows == 3
    assert result.kept_rows == 2
    assert result.removed_count == 1
    with out.open(newline="", encoding=CSV_WRITE_ENCODING) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["Question"] == "Dup"
    assert rows[1]["Question"] == "Unique"
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["removed_count"] == 1
    assert data["removed"][0]["removed_input_row"] == 2


def test_dedupe_stock_csv_file_rejects_bad_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing expected column"):
        dedupe_stock_csv_file(bad, tmp_path / "out.csv")
