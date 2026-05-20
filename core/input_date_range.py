"""Infer min/max calendar dates from uploaded Excel or CSV input workbooks."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
from pandas.api.types import is_numeric_dtype

# Substrings that suggest a *calendar* column. Omit "time": values like "2:30 pm"
# parse as today's date and would collapse inferred ranges to the upload day.
_DATE_NAME_HINTS: tuple[str, ...] = (
    "date",
    "release",
    "premiere",
    "air",
    "when",
    "start",
    "week",
    "day",
    "kickoff",
    "fixture",
)

_MONTH_OR_WEEKDAY = re.compile(
    r"(?i)\b(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b"
)
_CLOCKISH = re.compile(
    r"(?i)(^\s*\d{1,2}:\d{2}(\s*(am|pm))?\s*$|^\s*\d{1,2}\s*(am|pm)\s*$)"
)
_MAX_HEADER_ROWS = 12
_MAX_DATA_ROWS = 4000


def _normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)


def _hint_score(column_name: str) -> float:
    n = _normalize_header(column_name)
    return float(sum(1 for hint in _DATE_NAME_HINTS if hint in n))


def _series_mostly_clock_times(series: pd.Series) -> bool:
    """True when cells look like time-of-day only (e.g. MLS kickoff time column)."""

    s = series.dropna()
    if len(s) < 3:
        return False
    t = s.astype(str).str.strip()
    if t.str.contains(_MONTH_OR_WEEKDAY, regex=True).any():
        return False
    if t.str.contains(r"\b\d{4}\b", regex=True).any():
        return False
    if t.str.match(r"^\d{1,2}[-/][A-Za-z]", na=False).any():
        return False
    if t.str.match(r"^\d{4}-\d{2}-\d{2}", na=False).any():
        return False
    clockish = t.str.contains(_CLOCKISH, regex=True)
    return bool(clockish.mean() > 0.85)


def _parse_calendarish_series(series: pd.Series) -> pd.Series:
    """Parse to UTC; for yearless long-form dates (common in MLS schedules), try adding a year."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        out = pd.to_datetime(series, errors="coerce", utc=True)
    n = len(series)
    if n == 0:
        return out
    if int(out.notna().sum()) >= max(3, int(0.15 * n)):
        return out
    s = series.astype(str).str.strip()
    invalid = s.isin(("", "nan", "NaT", "None"))
    compact = s.str.match(r"^\d{4}-\d{2}-\d{2}\b", na=False) | s.str.match(
        r"^\d{1,2}[-/][A-Za-z]", na=False
    )
    need_fill = out.isna() & ~invalid & ~compact
    if not need_fill.any():
        return out
    best_out = out
    best_cnt = int(out.notna().sum())
    best_span_days = -1
    for year in (2026, 2025, 2027, 2024, 2028):
        s2 = s.where(~need_fill, s + ", " + str(year))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            trial = pd.to_datetime(s2, errors="coerce", utc=True)
        valid = trial.dropna()
        c = int(len(valid))
        span = int((valid.max() - valid.min()).days) if c > 1 else 0
        if c > best_cnt or (c == best_cnt and span > best_span_days):
            best_cnt = c
            best_span_days = span
            best_out = trial
        if c >= max(3, int(0.5 * n)):
            break
    return best_out


def _best_date_column_index(df: pd.DataFrame) -> int | None:
    if df.empty or df.shape[1] == 0:
        return None
    n = len(df)
    best_idx: int | None = None
    best_score = 0.0
    for idx in range(df.shape[1]):
        series = df.iloc[:, idx]
        if _series_mostly_clock_times(series):
            continue
        hint = _hint_score(str(df.columns[idx]))
        if is_numeric_dtype(series) and hint == 0:
            continue
        parsed = _parse_calendarish_series(series)
        ok = parsed.notna()
        cnt = int(ok.sum())
        if cnt == 0:
            continue
        vyear = parsed.dropna()
        if vyear.empty:
            continue
        if hint == 0 and int(vyear.dt.year.max()) <= 1970:
            continue
        frac = cnt / max(n, 1)
        if cnt < 2 and frac < 0.15:
            continue
        hint = _hint_score(str(df.columns[idx]))
        score = hint * 4.0 + frac * 12.0 + min(cnt, 80) * 0.02
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _dates_for_sheet(path: Path, sheet_name: str) -> list[pd.Timestamp]:
    """Pick one header row per sheet that yields the strongest date column."""

    best_series: list[pd.Timestamp] = []
    best_quality = -1.0
    try:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=_MAX_HEADER_ROWS + 2)
    except Exception:
        return []
    if raw.empty:
        return []
    max_header = min(_MAX_HEADER_ROWS, max(len(raw) - 1, 0))
    for header_idx in range(0, max_header + 1):
        try:
            df = pd.read_excel(
                path,
                sheet_name=sheet_name,
                header=header_idx,
                nrows=_MAX_DATA_ROWS,
            )
        except Exception:
            continue
        if df.empty or df.shape[1] == 0:
            continue
        col_idx = _best_date_column_index(df)
        if col_idx is None:
            continue
        parsed = _parse_calendarish_series(df.iloc[:, col_idx])
        valid = parsed.dropna()
        if valid.empty:
            continue
        quality = float(len(valid)) + _hint_score(str(df.columns[col_idx])) * 10.0
        if quality > best_quality:
            best_quality = quality
            best_series = valid.tolist()
    return best_series


def _dates_for_csv(path: Path) -> list[pd.Timestamp]:
    """Pick one header row for a CSV that yields the strongest date column."""

    best_series: list[pd.Timestamp] = []
    best_quality = -1.0
    for header_idx in range(0, _MAX_HEADER_ROWS + 1):
        try:
            df = pd.read_csv(path, header=header_idx, nrows=_MAX_DATA_ROWS)
        except Exception:
            continue
        if df.empty or df.shape[1] == 0:
            continue
        col_idx = _best_date_column_index(df)
        if col_idx is None:
            continue
        parsed = _parse_calendarish_series(df.iloc[:, col_idx])
        valid = parsed.dropna()
        if valid.empty:
            continue
        quality = float(len(valid)) + _hint_score(str(df.columns[col_idx])) * 10.0
        if quality > best_quality:
            best_quality = quality
            best_series = valid.tolist()
    return best_series


def infer_date_range_from_excel_paths(paths: Sequence[Path]) -> tuple[str | None, str | None]:
    """Return ``(start_iso, end_iso)`` as ``YYYY-MM-DD``, or ``(None, None)`` if no dates found."""

    stamps: list[pd.Timestamp] = []
    for path in paths:
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            stamps.extend(_dates_for_csv(path))
            continue
        if suffix not in {".xlsx", ".xls"}:
            continue
        try:
            book = pd.ExcelFile(path)
        except Exception:
            continue
        for sheet_name in book.sheet_names:
            stamps.extend(_dates_for_sheet(path, sheet_name))
    if not stamps:
        return None, None
    day_values = [pd.Timestamp(ts).date() for ts in stamps]
    return min(day_values).isoformat(), max(day_values).isoformat()
