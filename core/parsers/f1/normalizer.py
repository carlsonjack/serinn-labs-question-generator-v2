"""Formula 1 calendar normalization (schedule workbook → NormalizedEvent)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

import pandas as pd

from ..base import CategoryNormalizer
from ..contracts import (
    DetectedFile,
    NormalizedBundle,
    NormalizedEvent,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)
from ..registry import register_category_normalizer
from ..validators import validate_date_filter_results, validate_required_fields


def _f1_package_options(settings: Mapping[str, Any]) -> dict[str, Any]:
    pkgs = ((settings.get("inputs") or {}).get("packages")) or {}
    if not isinstance(pkgs, dict):
        return {}
    return pkgs.get("f1") or pkgs.get("F1") or {}


def _within_date_range(event_datetime: datetime, date_filter: dict[str, Any]) -> bool:
    start = date_filter.get("start")
    end = date_filter.get("end")
    event_date = event_datetime.date()
    if start and event_date < pd.to_datetime(start).date():
        return False
    if end and event_date > pd.to_datetime(end).date():
        return False
    return True


def _parse_row_datetime(raw: Any) -> datetime:
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Unparseable event datetime: {raw!r}")
    return ts.to_pydatetime()


@register_category_normalizer("f1")
class F1CategoryNormalizer(CategoryNormalizer):
    """Normalize F1 schedule rows into events (Race sessions by default)."""

    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        opts = _f1_package_options(settings)
        race_vals = opts.get("race_session_values") or ["Race"]
        race_norm = {str(v).strip().lower() for v in race_vals if str(v).strip()}
        home_ph = str(opts.get("placeholder_home_team") or "Driver_A").strip()
        away_ph = str(opts.get("placeholder_away_team") or "Driver_B").strip()

        event_file = next(
            (d for d in detected_files if d.source_role == SourceRole.EVENT_SOURCE),
            None,
        )
        if event_file is None:
            raise ValueError("F1 normalization requires an event_source workbook.")

        issues = validate_required_fields(
            file_path=str(event_file.file_path),
            source_role=event_file.source_role,
            field_mappings=event_file.field_mappings,
            required_fields=("event_id", "event_name", "event_date", "session_type"),
        )
        errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in issues if i.severity == ValidationSeverity.WARNING]
        if errors:
            return NormalizedBundle(issues=[*errors, *warnings])

        fm = event_file.field_mappings
        events: list[NormalizedEvent] = []
        date_filter = settings.get("date_filter") or {}

        for row in event_file.records:
            raw_session = str(row.get(fm["session_type"], "")).strip().lower()
            if raw_session not in race_norm:
                continue
            try:
                dt = _parse_row_datetime(row.get(fm["event_date"]))
            except ValueError as exc:
                warnings.append(
                    ValidationIssue(
                        code="bad_event_datetime",
                        message=str(exc),
                        severity=ValidationSeverity.WARNING,
                        file_path=str(event_file.file_path),
                        details={"event_id": row.get(fm.get("event_id"))},
                    )
                )
                continue

            if not _within_date_range(dt, date_filter):
                continue

            eid = str(row.get(fm["event_id"], "")).strip()
            ename = str(row.get(fm["event_name"], "")).strip()
            events.append(
                NormalizedEvent(
                    event_id=eid,
                    home_team=home_ph,
                    away_team=away_ph,
                    event_datetime=dt.isoformat(),
                    subcategory="F1",
                    event_display=ename or None,
                )
            )

        issues_out = [*warnings, *validate_date_filter_results(events)]
        prof = event_file.profile_used
        profiles = [prof] if prof is not None else []

        return NormalizedBundle(
            events=events,
            player_stats=[],
            issues=issues_out,
            profiles=profiles,
        )
