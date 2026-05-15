"""Regression: API payloads must be JSON-serializable (Flask jsonify)."""

from __future__ import annotations

import json
from datetime import time

import pandas as pd

from core.json_safe import json_safe
from core.parsers.detector import workbook_snapshot


def test_json_safe_time_and_round_trip() -> None:
    raw = {"t": time(19, 0, 0), "n": 1}
    out = json_safe(raw)
    assert out["t"] == "19:00:00"
    json.dumps(out)


def test_workbook_snapshot_excel_time_column_is_json_serializable(
    tmp_path,
) -> None:
    p = tmp_path / "with_time.xlsx"
    pd.DataFrame([{"Kickoff": time(19, 0, 0), "Matchup": "A v B"}]).to_excel(
        p, index=False
    )
    snap = workbook_snapshot(p)
    json.dumps(snap)
