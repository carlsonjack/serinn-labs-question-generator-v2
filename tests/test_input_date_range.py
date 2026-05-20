"""Date range inference from Excel input workbooks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.input_date_range import infer_date_range_from_excel_paths


def test_infer_date_range_from_release_column(tmp_path: Path) -> None:
    path = tmp_path / "releases.xlsx"
    pd.DataFrame(
        [
            {"Release Date": "June 5, 2026", "Album Title": "A"},
            {"Release Date": "June 26, 2026", "Album Title": "B"},
        ]
    ).to_excel(path, index=False)

    start, end = infer_date_range_from_excel_paths([path])
    assert start == "2026-06-05"
    assert end == "2026-06-26"


def test_infer_date_range_mls_yearless_date_plus_time_column(tmp_path: Path) -> None:
    """MLS-style weekday+month day without year; Time column must not drive the calendar span."""

    schedule = tmp_path / "schedule.xlsx"
    pd.DataFrame(
        [
            {"Date": "Saturday, February 21", "Match": "A vs. B", "Time": "2:30 pm"},
            {"Date": "Sunday, October 26", "Match": "C vs. D", "Time": "3:00 pm"},
        ]
    ).to_excel(schedule, index=False)

    start, end = infer_date_range_from_excel_paths([schedule])
    assert start == "2026-02-21"
    assert end == "2026-10-26"


def test_infer_date_range_empty_when_no_dates(tmp_path: Path) -> None:
    path = tmp_path / "nums.xlsx"
    pd.DataFrame([{"Ticker": "AAPL", "Price": 1.0}, {"Ticker": "MSFT", "Price": 2.0}]).to_excel(
        path, index=False
    )

    start, end = infer_date_range_from_excel_paths([path])
    assert start is None
    assert end is None


def test_infer_date_range_from_csv_start_date_column(tmp_path: Path) -> None:
    path = tmp_path / "schedule.csv"
    pd.DataFrame(
        [
            {"start_date": "2026-03-05", "event_name": "Arnold Palmer Invitational"},
            {"start_date": "2026-04-09", "event_name": "Masters Tournament"},
        ]
    ).to_csv(path, index=False)

    start, end = infer_date_range_from_excel_paths([path])
    assert start == "2026-03-05"
    assert end == "2026-04-09"
