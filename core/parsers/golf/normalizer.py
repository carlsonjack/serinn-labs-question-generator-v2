"""PGA / golf calendar + world-rankings normalization."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import pandas as pd

from ..base import CategoryNormalizer
from ..contracts import DetectedFile, NormalizedBundle, NormalizedEvent, PlayerStatRecord, SourceRole, ValidationIssue, ValidationSeverity
from ..field_events import resolve_field_event_id, resolve_field_event_teams
from ..package_options import field_team_code, skip_status_values
from ..registry import register_category_normalizer
from ..stat_keys import stat_storage_key
from ..validators import validate_date_filter_results


def _within_date_range(event_datetime: pd.Timestamp, date_filter: dict[str, Any]) -> bool:
    start = date_filter.get("start")
    end = date_filter.get("end")
    event_date = event_datetime.date()
    if start and event_date < pd.to_datetime(start).date():
        return False
    if end and event_date > pd.to_datetime(end).date():
        return False
    return True


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


def _slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")
    return slug or "event"


def _clean_event_name(name: str) -> str:
    cleaned = re.sub(r"\s*\[?\s*CANCELLED\s*\]?\s*", "", name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@register_category_normalizer("golf")
class GolfCategoryNormalizer(CategoryNormalizer):
    """Normalize PGA schedule + world rankings into events and field player stats."""

    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        event_file = next(
            (d for d in detected_files if d.source_role == SourceRole.EVENT_SOURCE),
            None,
        )
        if event_file is None:
            raise ValueError("Golf normalization requires an event_source (schedule) workbook.")

        metric_file = next(
            (d for d in detected_files if d.source_role == SourceRole.METRIC_SOURCE),
            None,
        )

        category_key = "golf"
        skip_status = skip_status_values(settings, category_key)
        field_code = field_team_code(settings, category_key)
        date_filter = settings.get("date_filter") or {}

        fm = event_file.field_mappings
        date_col = fm.get("event_date") or fm.get("start_date") or "start_date"
        name_col = fm.get("event_display") or fm.get("event_name") or "event_name"
        status_col = fm.get("status") or "status"

        events: list[NormalizedEvent] = []
        warnings: list[ValidationIssue] = []

        for idx, row in enumerate(event_file.records, start=event_file.header_row_index + 2):
            raw_name = _cell(row, name_col)
            display = _clean_event_name(raw_name)
            if not display:
                continue
            if "cancelled" in raw_name.lower() or "canceled" in raw_name.lower():
                continue
            status_val = _cell(row, status_col).lower()
            if skip_status and status_val in skip_status:
                continue

            try:
                dt = pd.to_datetime(_cell(row, date_col), errors="coerce")
                if pd.isna(dt):
                    continue
                ts = pd.Timestamp(dt)
            except (TypeError, ValueError):
                continue

            if not _within_date_range(ts, date_filter):
                continue

            fallback_id = _slug(f"{ts.date().isoformat()}-{display}")
            event_id = resolve_field_event_id(row, fm, fallback=fallback_id)
            home_team, away_team = resolve_field_event_teams(row, fm, settings, category_key)
            metadata = {
                k: _cell(row, col)
                for k, col in fm.items()
                if k
                not in {
                    "event_date",
                    "start_date",
                    "event_name",
                    "event_display",
                    "event_id",
                    "home_team",
                    "away_team",
                }
                and col in row
                and _cell(row, col)
            }
            if status_val:
                metadata.setdefault("status", status_val)

            events.append(
                NormalizedEvent(
                    event_id=event_id,
                    home_team=home_team,
                    away_team=away_team,
                    event_datetime=ts.isoformat(timespec="seconds"),
                    subcategory="Golf",
                    event_display=display,
                    metadata=metadata,
                )
            )

        players: list[PlayerStatRecord] = []
        if metric_file is not None:
            mfm = metric_file.field_mappings
            player_col = mfm.get("player_name") or "PLAYER"
            for idx, row in enumerate(metric_file.records, start=metric_file.header_row_index + 2):
                player_name = _cell(row, player_col)
                if not player_name:
                    continue
                stat_values: dict[str, float] = {}
                for col in metric_file.columns:
                    if col == player_col:
                        continue
                    val = _coerce_float(row.get(col))
                    if val is not None:
                        stat_values[stat_storage_key(col)] = val
                players.append(
                    PlayerStatRecord(
                        player_name=player_name,
                        team=field_code,
                        source_team=field_code,
                        stat_values=stat_values,
                        source_sheet=metric_file.sheet_name,
                        row_number=idx,
                        metadata={},
                    )
                )

        issues = [*warnings, *validate_date_filter_results(events)]
        if not events:
            issues.append(
                ValidationIssue(
                    code="no_events_normalized",
                    message="No golf tournament rows in range after filtering.",
                    severity=ValidationSeverity.ERROR,
                )
            )
        if metric_file is not None and not players:
            issues.append(
                ValidationIssue(
                    code="no_player_stats_normalized",
                    message="No player ranking rows were normalized.",
                    severity=ValidationSeverity.ERROR,
                )
            )

        profiles = [p for p in (event_file.profile_used, metric_file.profile_used if metric_file else None) if p]
        return NormalizedBundle(
            events=events,
            player_stats=players,
            issues=issues,
            profiles=profiles,
        )
