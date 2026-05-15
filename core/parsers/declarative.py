"""Deterministic executor for approved declarative normalizer profiles."""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil.parser import ParserError, UnknownTimezoneWarning, parse as parse_datetime

from core.json_safe import json_safe

from .contracts import (
    DetectedFile,
    EventDatetimeSpec,
    EventIdSpec,
    MatchupSplitSpec,
    ContentEntity,
    NormalizationSpec,
    NormalizedBundle,
    NormalizedEvent,
    PlayerStatRecord,
    SourceNormalizationSpec,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)


def _iso_timestamp_seconds(ts: pd.Timestamp) -> str:
    """Naive ISO 8601 with seconds (matches :func:`core.date_rules._format_iso_naive`)."""

    dt = ts.to_pydatetime()
    if dt.microsecond:
        dt = dt.replace(microsecond=0)
    return dt.isoformat(timespec="seconds")


def validate_normalization_spec(spec: NormalizationSpec) -> list[ValidationIssue]:
    """Return deterministic validation issues for a declarative spec."""

    issues: list[ValidationIssue] = []
    if not spec.package_key.strip():
        issues.append(_error("invalid_normalization_spec", "package_key is required"))
    if not spec.sources:
        issues.append(_error("invalid_normalization_spec", "At least one source is required"))

    roles = {source.source_role for source in spec.sources.values()}
    entity_only = SourceRole.EVENT_SOURCE not in roles and SourceRole.ENTITY_SOURCE in roles
    if SourceRole.EVENT_SOURCE not in roles and not entity_only:
        issues.append(_error("invalid_normalization_spec", "event_source is required"))

    for slot_id, source in spec.sources.items():
        if not source.file_pattern.strip():
            issues.append(
                _error(
                    "invalid_normalization_spec",
                    f"Source {slot_id!r} requires file_pattern",
                )
            )
        if source.source_role == SourceRole.EVENT_SOURCE:
            _validate_event_source(slot_id, source, issues)
        elif source.source_role == SourceRole.METRIC_SOURCE:
            _validate_metric_source(slot_id, source, issues)
        elif source.source_role == SourceRole.ENTITY_SOURCE and entity_only:
            _validate_entity_source(slot_id, source, issues)

    return issues


def execute_normalization_spec(
    spec: NormalizationSpec,
    detected_files: Sequence[DetectedFile],
    settings: Mapping[str, Any],
) -> NormalizedBundle:
    """Normalize detected files according to an approved declarative spec."""

    issues = validate_normalization_spec(spec)
    if any(i.severity == ValidationSeverity.ERROR for i in issues):
        return NormalizedBundle(issues=issues)

    events: list[NormalizedEvent] = []
    entities: list[ContentEntity] = []
    players: list[PlayerStatRecord] = []

    event_spec = _source_for_role(spec, SourceRole.EVENT_SOURCE)
    event_file = _detected_for_spec_source(event_spec, detected_files)
    entity_spec = _source_for_role(spec, SourceRole.ENTITY_SOURCE)
    entity_file = _detected_for_spec_source(entity_spec, detected_files)
    if event_spec is None and entity_spec is not None and entity_file is not None:
        entities, entity_issues = _normalize_entities(entity_spec, entity_file)
        issues.extend(entity_issues)
        return NormalizedBundle(entities=entities, issues=issues)
    if event_spec is None or event_file is None:
        return NormalizedBundle(
            issues=[_error("missing_event_source", "No event_source file was detected")]
        )

    event_edt = event_spec.event_datetime or EventDatetimeSpec()
    team_tz_map: dict[str, str] = {}
    if not (event_edt.timezone and str(event_edt.timezone).strip()):
        from core.event_timezone_infer import infer_team_timezones_from_names

        homes = _unique_home_teams_for_timezone_infer(event_spec, event_file)
        team_tz_map = infer_team_timezones_from_names(homes, settings)

    events, event_issues = _normalize_events(
        event_spec, event_file, spec, settings, team_tz=team_tz_map
    )
    issues.extend(event_issues)

    metric_spec = _source_for_role(spec, SourceRole.METRIC_SOURCE)
    metric_file = _detected_for_spec_source(metric_spec, detected_files)
    if metric_spec is not None and metric_file is not None:
        players, player_issues = _normalize_player_stats(metric_spec, metric_file)
        issues.extend(player_issues)

    return NormalizedBundle(events=events, entities=entities, player_stats=players, issues=issues)


def preview_normalization_spec(
    spec: NormalizationSpec,
    detected_files: Sequence[DetectedFile],
    settings: Mapping[str, Any],
    *,
    event_limit: int = 5,
    player_limit: int = 10,
) -> dict[str, Any]:
    """Return a bounded JSON-friendly normalization preview."""

    bundle = execute_normalization_spec(spec, detected_files, settings)
    return json_safe(
        {
            "events": [e.__dict__ for e in bundle.events[:event_limit]],
            "entities": [e.__dict__ for e in bundle.entities[:player_limit]],
            "player_stats": [p.__dict__ for p in bundle.player_stats[:player_limit]],
            "issues": [_issue_to_dict(i) for i in bundle.issues],
            "event_count": len(bundle.events),
            "entity_count": len(bundle.entities),
            "player_stat_count": len(bundle.player_stats),
        }
    )


def _validate_event_source(
    slot_id: str, source: SourceNormalizationSpec, issues: list[ValidationIssue]
) -> None:
    has_home_away = {"home_team", "away_team"} <= set(source.field_mappings)
    has_matchup = source.matchup_split is not None
    if not (has_home_away or has_matchup):
        issues.append(
            _error(
                "invalid_event_mapping",
                f"Event source {slot_id!r} needs home_team/away_team mappings or matchup_split",
            )
        )
    has_datetime = "event_datetime" in source.field_mappings or source.event_datetime
    has_date = "event_date" in source.field_mappings
    if not (has_datetime or has_date):
        issues.append(
            _error(
                "invalid_event_mapping",
                f"Event source {slot_id!r} needs event_datetime or event_date mapping",
            )
        )


def _validate_metric_source(
    slot_id: str, source: SourceNormalizationSpec, issues: list[ValidationIssue]
) -> None:
    missing = [f for f in ("player_name", "team") if f not in source.field_mappings]
    if missing:
        issues.append(
            _error(
                "invalid_metric_mapping",
                f"Metric source {slot_id!r} is missing required mappings: {missing}",
            )
        )


def _validate_entity_source(
    slot_id: str, source: SourceNormalizationSpec, issues: list[ValidationIssue]
) -> None:
    fields = set(source.field_mappings)
    if {"company_name", "ticker"} <= fields:
        return
    if "entity_name" in fields:
        return
    if "title" in fields:
        return
    issues.append(
        _error(
            "invalid_entity_mapping",
            f"Entity source {slot_id!r} needs company_name/ticker mappings, entity_name, or title",
        )
        )


def _unique_home_teams_for_timezone_infer(
    source: SourceNormalizationSpec,
    detected: DetectedFile,
) -> list[str]:
    """Stable unique home team labels for AI timezone lookup (profile timezone unset)."""

    homes: set[str] = set()
    for row in detected.records:
        try:
            home, _ = _event_teams(row, source)
        except ValueError:
            continue
        if home.strip():
            homes.add(home.strip())
    return sorted(homes)


def _normalize_events(
    source: SourceNormalizationSpec,
    detected: DetectedFile,
    spec: NormalizationSpec,
    settings: Mapping[str, Any],
    *,
    team_tz: Mapping[str, str] | None = None,
) -> tuple[list[NormalizedEvent], list[ValidationIssue]]:
    events: list[NormalizedEvent] = []
    issues: list[ValidationIssue] = []
    date_filter = settings.get("date_filter") or {}

    team_tz = team_tz or {}
    skipped_by_filter = 0
    failed_parse = 0
    total_rows = len(detected.records)
    for idx, row in enumerate(detected.records, start=detected.header_row_index + 2):
        try:
            home_team, away_team = _event_teams(row, source)
            tz_override = team_tz.get(home_team.strip()) if team_tz else None
            dt = _event_datetime(row, source, date_filter, timezone_override=tz_override)
            if not _within_date_range(dt, date_filter):
                skipped_by_filter += 1
                continue
            event_id = _event_id(row, source, idx)
            display = _cell(row, source.field_mappings.get("event_display"))
            if not display and source.matchup_split is not None:
                display = _cell(row, source.matchup_split.source_column)
            events.append(
                NormalizedEvent(
                    event_id=event_id,
                    home_team=home_team,
                    away_team=away_team,
                    event_datetime=_iso_timestamp_seconds(dt),
                    subcategory=spec.package_key,
                    event_display=display or None,
                    metadata=_metadata(row, source),
                )
            )
        except ValueError as exc:
            failed_parse += 1
            issues.append(
                ValidationIssue(
                    code="declarative_event_row_error",
                    message=str(exc),
                    severity=ValidationSeverity.WARNING,
                    file_path=str(detected.file_path),
                    source_role=detected.source_role,
                    details={"row_number": idx},
                )
            )

    if not events:
        df = date_filter if isinstance(date_filter, dict) else {}
        window = ""
        if df.get("start") or df.get("end"):
            window = f" date_filter is {df.get('start')!r} to {df.get('end')!r}."
        if total_rows == 0:
            msg = "No data rows under the detected header for the schedule sheet."
        elif failed_parse == total_rows:
            msg = (
                f"All {total_rows} schedule row(s) failed to parse (see row warnings). "
                "Check Match/home/away mapping and Date + Time columns."
            )
        elif skipped_by_filter == total_rows:
            msg = (
                f"All {total_rows} schedule row(s) parsed but none fall within the date window.{window} "
                "Widen date_filter in settings (or the upload auto date range) so it includes match days."
            )
        else:
            msg = (
                f"No event rows in range: {skipped_by_filter} row(s) outside date_filter,"
                f" {failed_parse} parse error(s), {total_rows} total.{window}"
            )
        issues.append(_error("no_events_normalized", msg))
    return events, issues


def _normalize_player_stats(
    source: SourceNormalizationSpec, detected: DetectedFile
) -> tuple[list[PlayerStatRecord], list[ValidationIssue]]:
    players: list[PlayerStatRecord] = []
    issues: list[ValidationIssue] = []
    player_col = source.field_mappings["player_name"]
    team_col = source.field_mappings["team"]

    for idx, row in enumerate(detected.records, start=detected.header_row_index + 2):
        player_name = _cell(row, player_col)
        team = _cell(row, team_col)
        if not player_name or not team:
            continue
        stat_values: dict[str, float] = {}
        for stat_key, column in source.metric_mappings.items():
            raw = row.get(column)
            val = _coerce_float(raw)
            if val is not None:
                stat_values[str(stat_key).upper()] = val
        players.append(
            PlayerStatRecord(
                player_name=player_name,
                team=team,
                source_team=team,
                stat_values=stat_values,
                source_sheet=detected.sheet_name,
                row_number=idx,
                metadata=_metadata(row, source),
            )
        )

    if not players:
        issues.append(_error("no_player_stats_normalized", "No player stat rows were normalized"))
    return players, issues


def _normalize_entities(
    source: SourceNormalizationSpec, detected: DetectedFile
) -> tuple[list[ContentEntity], list[ValidationIssue]]:
    entities: list[ContentEntity] = []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for idx, row in enumerate(detected.records, start=detected.header_row_index + 2):
        company = _cell(row, source.field_mappings.get("company_name"))
        ticker = _cell(row, source.field_mappings.get("ticker"))
        entity_name = _cell(row, source.field_mappings.get("entity_name"))
        title = _cell(row, source.field_mappings.get("title"))
        artist = _cell(row, source.field_mappings.get("artist"))
        release_date = _cell(row, source.field_mappings.get("release_date"))
        content_type = _cell(row, source.field_mappings.get("content_type"))
        topic_import_id = _cell(row, source.field_mappings.get("topic_import_id"))
        entity_id = (ticker or entity_name or title or company).strip()
        if not entity_id:
            continue
        if title and artist:
            entity_id = _slug("-".join(part for part in (title, artist, release_date) if part))
        else:
            entity_id = entity_id.upper() if ticker else _slug(entity_id)
        if entity_id in seen:
            issues.append(
                ValidationIssue(
                    code="duplicate_entity",
                    message=f"Duplicate entity id {entity_id!r}",
                    severity=ValidationSeverity.WARNING,
                    file_path=str(detected.file_path),
                    source_role=detected.source_role,
                    details={"row_number": idx},
                )
            )
            continue
        seen.add(entity_id)
        if title and artist:
            display_name = f"{title} by {artist}"
        elif title:
            display_name = title
        else:
            display_name = f"{company} ({ticker.upper()})" if company and ticker else entity_name or company or entity_id
        metadata = _metadata(row, source)
        for key, column in source.field_mappings.items():
            value = _cell(row, column)
            if value:
                metadata.setdefault(key, value)
        if company:
            metadata.setdefault("company_name", company)
        if ticker:
            metadata.setdefault("ticker", ticker.upper())
        for key, value in (
            ("title", title),
            ("artist", artist),
            ("release_date", release_date),
            ("content_type", content_type),
        ):
            if value:
                metadata.setdefault(key, value)
        entities.append(
            ContentEntity(
                entity_id=entity_id,
                display_name=display_name,
                entity_type="stock" if ticker else content_type or "content",
                topic_import_id=topic_import_id or None,
                metadata=metadata,
            )
        )

    if not entities:
        issues.append(_error("no_entities_normalized", "No entity rows were normalized"))
    return entities, issues


def _event_teams(row: Mapping[str, Any], source: SourceNormalizationSpec) -> tuple[str, str]:
    home = _cell(row, source.field_mappings.get("home_team"))
    away = _cell(row, source.field_mappings.get("away_team"))
    if home and away:
        return home, away

    split = source.matchup_split
    if split is None:
        raise ValueError("Missing home_team/away_team and matchup_split")
    left, right = _split_matchup(_cell(row, split.source_column), split)
    if split.left_team_field == "away_team":
        away = left
    else:
        home = left
    if split.right_team_field == "home_team":
        home = right
    else:
        away = right
    if not home or not away:
        raise ValueError("Could not derive both teams from matchup")
    return home, away


def _split_matchup(value: str, spec: MatchupSplitSpec) -> tuple[str, str]:
    parts = re.split(spec.delimiter_pattern, value, maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Could not split matchup {value!r}")
    return parts[0].strip(), parts[1].strip()


def _zoneinfo_from_profile_string(name: str) -> ZoneInfo:
    """Resolve IANA name or a few legacy abbreviations used in YAML profiles."""

    key = str(name or "").strip()
    if not key:
        raise ValueError("Empty timezone name")
    try:
        return ZoneInfo(key)
    except Exception:
        pass
    aliases = {
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "CST": "America/Chicago",
        "CDT": "America/Chicago",
        "MST": "America/Denver",
        "MDT": "America/Denver",
        "PST": "America/Los_Angeles",
        "PDT": "America/Los_Angeles",
    }
    mapped = aliases.get(key.upper())
    if mapped:
        return ZoneInfo(mapped)
    raise ValueError(f"Unknown timezone: {name!r}")


def _event_timestamp_to_naive_utc(ts: pd.Timestamp, tz_name: str | None) -> pd.Timestamp:
    """Interpret naive *ts* as local in *tz_name*, then return naive UTC (pandas)."""

    if tz_name is None or not str(tz_name).strip():
        return ts
    zi = _zoneinfo_from_profile_string(str(tz_name))
    if ts.tzinfo is not None:
        return ts.tz_convert(dt_timezone.utc).tz_localize(None)
    aware = ts.tz_localize(zi)
    utc = aware.tz_convert(dt_timezone.utc)
    return utc.tz_localize(None)


def _event_datetime(
    row: Mapping[str, Any],
    source: SourceNormalizationSpec,
    date_filter: Mapping[str, Any],
    *,
    timezone_override: str | None = None,
) -> pd.Timestamp:
    spec = source.event_datetime or EventDatetimeSpec()
    tz_profile = str(spec.timezone).strip() if spec.timezone else ""
    tz_ov = str(timezone_override or "").strip()
    effective_tz = tz_profile or tz_ov or None
    if spec.datetime_column:
        ts = _parse_datetime(_cell(row, spec.datetime_column), date_filter)
        return _event_timestamp_to_naive_utc(ts, effective_tz)
    if "event_datetime" in source.field_mappings:
        ts = _parse_datetime(_cell(row, source.field_mappings["event_datetime"]), date_filter)
        return _event_timestamp_to_naive_utc(ts, effective_tz)

    date_col = spec.date_column or source.field_mappings.get("event_date")
    time_col = spec.time_column or source.field_mappings.get("event_time")
    date_val = _cell(row, date_col)
    time_raw = _cell(row, time_col) if time_col else ""
    time_val = str(time_raw).strip() if time_raw not in (None, "") else ""
    if not time_val:
        time_val = "00:00:00"
    raw = f"{date_val} {time_val}".strip()
    if not raw:
        raise ValueError("Missing event datetime")
    ts = _parse_datetime(raw, date_filter)
    return _event_timestamp_to_naive_utc(ts, effective_tz)


def _parse_datetime(raw: str, date_filter: Mapping[str, Any]) -> pd.Timestamp:
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UnknownTimezoneWarning)
                parsed = parse_datetime(
                    raw,
                    default=datetime(_default_event_year(date_filter), 1, 1),
                    fuzzy=True,
                    ignoretz=True,
                )
        except (ParserError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Unparseable event datetime: {raw!r}") from exc
    return pd.Timestamp(parsed)


def _default_event_year(date_filter: Mapping[str, Any]) -> int:
    for key in ("start", "end"):
        raw = date_filter.get(key)
        if not raw:
            continue
        parsed = pd.to_datetime(raw, errors="coerce")
        if not pd.isna(parsed):
            return int(parsed.year)
    return datetime.now().year


def _event_id(row: Mapping[str, Any], source: SourceNormalizationSpec, row_number: int) -> str:
    mapped = _cell(row, source.field_mappings.get("event_id"))
    if mapped:
        return _slug(mapped)
    spec = source.event_id or EventIdSpec()
    parts = [_cell(row, column) for column in spec.source_columns]
    raw = "-".join(p for p in parts if p)
    return _slug(raw or f"event-{row_number}")


def _metadata(row: Mapping[str, Any], source: SourceNormalizationSpec) -> dict[str, Any]:
    return {
        key: row.get(column)
        for key, column in source.metadata_mappings.items()
        if column in row and row.get(column) not in ("", None)
    }


def _within_date_range(event_datetime: pd.Timestamp, date_filter: Mapping[str, Any]) -> bool:
    start = date_filter.get("start")
    end = date_filter.get("end")
    event_date = event_datetime.date()
    if start and event_date < pd.to_datetime(start).date():
        return False
    if end and event_date > pd.to_datetime(end).date():
        return False
    return True


def _source_for_role(
    spec: NormalizationSpec, role: SourceRole
) -> SourceNormalizationSpec | None:
    return next((s for s in spec.sources.values() if s.source_role == role), None)


def _detected_for_spec_source(
    source: SourceNormalizationSpec | None,
    detected_files: Sequence[DetectedFile],
) -> DetectedFile | None:
    """Resolve the workbook row for this spec source.

    Prefer ``(source_role, basename(file_pattern))`` so schedule+stats packages stay
    strict. If that misses (e.g. UI slot id ``event_source`` forced ``EVENT_SOURCE`` on
    a file while the saved declarative spec uses ``entity_source`` for the same
    workbook), fall back to basename-only match so entity-only profiles still run.
    """

    if source is None or not str(source.file_pattern or "").strip():
        return None
    pattern = Path(str(source.file_pattern).strip()).name
    role_matches = [
        d
        for d in detected_files
        if d.source_role == source.source_role and d.file_path.name == pattern
    ]
    if len(role_matches) == 1:
        return role_matches[0]
    name_matches = [d for d in detected_files if d.file_path.name == pattern]
    if source.sheet_name:
        sheet_hits = [d for d in name_matches if d.sheet_name == source.sheet_name]
        if len(sheet_hits) == 1:
            return sheet_hits[0]
        role_sheet = [d for d in role_matches if d.sheet_name == source.sheet_name]
        if len(role_sheet) == 1:
            return role_sheet[0]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(role_matches) > 1:
        return role_matches[0]
    same_role = [d for d in detected_files if d.source_role == source.source_role]
    if len(same_role) == 1:
        return same_role[0]
    return None


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


def _error(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=ValidationSeverity.ERROR,
    )


def _issue_to_dict(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "file_path": issue.file_path,
        "source_role": issue.source_role.value if issue.source_role else None,
        "field_name": issue.field_name,
        "details": issue.details,
    }
