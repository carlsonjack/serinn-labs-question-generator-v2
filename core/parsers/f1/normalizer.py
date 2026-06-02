"""Formula 1 calendar + driver standings normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

import pandas as pd

from ..base import CategoryNormalizer
from ..contracts import (
    DetectedFile,
    NormalizedBundle,
    NormalizedEvent,
    PlayerStatRecord,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)
from ..field_events import resolve_field_event_teams
from ..package_options import field_team_code
from ..registry import register_category_normalizer
from ..stat_keys import stat_storage_key
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


def _cell(row: Mapping[str, Any], column: str | None) -> str:
    if not column:
        return ""
    return str(row.get(column, "")).strip()


def _coerce_float(raw: Any) -> float | None:
    if raw in ("", None):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@register_category_normalizer("f1")
class F1CategoryNormalizer(CategoryNormalizer):
    """Normalize F1 schedule rows and optional driver standings."""

    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        opts = _f1_package_options(settings)
        race_vals = opts.get("race_session_values") or ["Race"]
        race_norm = {str(v).strip().lower() for v in race_vals if str(v).strip()}
        field_code = field_team_code(settings, "f1")

        event_file = next(
            (d for d in detected_files if d.source_role == SourceRole.EVENT_SOURCE),
            None,
        )
        if event_file is None:
            raise ValueError("F1 normalization requires an event_source workbook.")

        metric_file = next(
            (d for d in detected_files if d.source_role == SourceRole.METRIC_SOURCE),
            None,
        )

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
            home_team, away_team = resolve_field_event_teams(row, fm, settings, "f1")
            events.append(
                NormalizedEvent(
                    event_id=eid,
                    home_team=home_team,
                    away_team=away_team,
                    event_datetime=dt.isoformat(),
                    subcategory="F1",
                    event_display=ename or None,
                )
            )

        players: list[PlayerStatRecord] = []
        if metric_file is not None:
            mfm = metric_file.field_mappings
            player_col = mfm.get("player_name") or "DRIVER"
            team_col = mfm.get("team")
            skip_cols = {player_col}
            if team_col:
                skip_cols.add(team_col)
            for idx, row in enumerate(
                metric_file.records,
                start=metric_file.header_row_index + 2,
            ):
                player_name = _cell(row, player_col)
                if not player_name:
                    continue
                constructor = _cell(row, team_col) if team_col else ""
                stat_values: dict[str, float] = {}
                for col in metric_file.columns:
                    if col in skip_cols:
                        continue
                    val = _coerce_float(row.get(col))
                    if val is not None:
                        stat_values[stat_storage_key(col)] = val
                players.append(
                    PlayerStatRecord(
                        player_name=player_name,
                        team=field_code,
                        source_team=constructor,
                        stat_values=stat_values,
                        source_sheet=metric_file.sheet_name,
                        row_number=idx,
                        metadata={},
                    )
                )

        issues_out = [*warnings, *validate_date_filter_results(events)]
        if metric_file is not None and not players:
            issues_out.append(
                ValidationIssue(
                    code="no_player_stats_normalized",
                    message="No driver standings rows were normalized.",
                    severity=ValidationSeverity.WARNING,
                    file_path=str(metric_file.file_path),
                )
            )

        profiles = [
            p
            for p in (
                event_file.profile_used,
                metric_file.profile_used if metric_file else None,
            )
            if p is not None
        ]

        return NormalizedBundle(
            events=events,
            player_stats=players,
            issues=issues_out,
            profiles=profiles,
        )
