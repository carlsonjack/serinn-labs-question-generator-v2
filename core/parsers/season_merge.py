"""Shared helpers for merging multi-sheet season workbooks."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable
import unicodedata

from .contracts import ValidationIssue, ValidationSeverity
from .detector import DetectedSheet, DetectionResult

_IDENTITY_FIELDS = {"player_id", "player_name", "team", "league"}


@dataclass
class MergedSeasonRow:
    """One merged player row composed from stats and association sheets."""

    stats_row: dict[str, Any]
    association_row: dict[str, Any] | None
    merged_row: dict[str, Any]
    join_value: str
    stats_sheet_name: str
    association_sheet_name: str | None


@dataclass
class SeasonMergeResult:
    """Result of selecting and optionally merging workbook sheets."""

    stats_sheet: DetectedSheet
    association_sheet: DetectedSheet | None
    merged_rows: list[MergedSeasonRow]
    issues: list[ValidationIssue] = field(default_factory=list)
    join_strategy: str = "player_name"
    used_multi_sheet: bool = False


def merge_metric_detection(detection: DetectionResult) -> SeasonMergeResult:
    """Build a merge-ready metric view from a workbook detection result."""

    selected_sheet = _selected_sheet(detection)
    profile_options = (
        dict(detection.detected_file.profile_used.normalizer_options)
        if detection.detected_file.profile_used is not None
        else {}
    )

    stats_sheet, association_sheet = _select_metric_sheets(
        detection.sheet_detections,
        selected_sheet=selected_sheet,
        profile_options=profile_options,
    )
    if association_sheet is None or association_sheet.sheet_name == stats_sheet.sheet_name:
        return SeasonMergeResult(
            stats_sheet=stats_sheet,
            association_sheet=None,
            merged_rows=[
                MergedSeasonRow(
                    stats_row=row,
                    association_row=None,
                    merged_row=dict(row),
                    join_value="",
                    stats_sheet_name=stats_sheet.sheet_name,
                    association_sheet_name=None,
                )
                for row in stats_sheet.records
            ],
        )

    join_strategy = (
        "player_id"
        if "player_id" in stats_sheet.field_mappings
        and "player_id" in association_sheet.field_mappings
        else "player_name"
    )
    issues: list[ValidationIssue] = []
    association_lookup = _build_association_lookup(
        association_sheet,
        join_strategy=join_strategy,
        issues=issues,
    )
    player_column = _resolve_column(stats_sheet, "player_name")
    team_column = _resolve_column(stats_sheet, "team")

    merged_rows: list[MergedSeasonRow] = []
    for row in stats_sheet.records:
        join_value = _row_join_value(stats_sheet, row, join_strategy)
        association_row = association_lookup.get(join_value) if join_value else None
        if association_row is None and join_value:
            player_name = str(row.get(player_column, "")).strip() if player_column else ""
            issues.append(
                ValidationIssue(
                    code="season_merge_unmatched_player",
                    message=(
                        f"Could not map player {player_name or join_value!r} from "
                        f"{stats_sheet.sheet_name} to {association_sheet.sheet_name}."
                    ),
                    severity=ValidationSeverity.WARNING,
                    file_path=str(detection.detected_file.file_path),
                    details={
                        "join_strategy": join_strategy,
                        "join_value": join_value,
                        "stats_sheet": stats_sheet.sheet_name,
                        "association_sheet": association_sheet.sheet_name,
                    },
                )
            )
        merged_row = dict(row)
        if association_row:
            merged_row.update(association_row)
        elif team_column:
            # Keep the historical-team fallback for backward compatibility.
            merged_row[team_column] = row.get(team_column, "")
        merged_rows.append(
            MergedSeasonRow(
                stats_row=row,
                association_row=association_row,
                merged_row=merged_row,
                join_value=join_value,
                stats_sheet_name=stats_sheet.sheet_name,
                association_sheet_name=association_sheet.sheet_name,
            )
        )

    return SeasonMergeResult(
        stats_sheet=stats_sheet,
        association_sheet=association_sheet,
        merged_rows=merged_rows,
        issues=issues,
        join_strategy=join_strategy,
        used_multi_sheet=True,
    )


def infer_merge_profile_options(detection: DetectionResult) -> dict[str, Any]:
    """Summarize heuristic merge choices for profile persistence."""

    merge_result = merge_metric_detection(detection)
    options: dict[str, Any] = {
        "stats_sheet_name": merge_result.stats_sheet.sheet_name,
        "join_strategy": merge_result.join_strategy,
    }
    if merge_result.association_sheet is not None:
        options["association_sheet_name"] = merge_result.association_sheet.sheet_name
    return options


def _selected_sheet(detection: DetectionResult) -> DetectedSheet:
    for sheet in detection.sheet_detections:
        if sheet.sheet_name == detection.detected_file.sheet_name:
            return sheet
    return DetectedSheet(
        sheet_name=detection.detected_file.sheet_name or detection.detected_file.file_path.stem,
        sheet_index=0,
        source_role=detection.detected_file.source_role,
        header_row_index=detection.detected_file.header_row_index,
        columns=detection.detected_file.columns,
        field_mappings=detection.detected_file.field_mappings,
        confidence=detection.detected_file.confidence,
        records=detection.detected_file.records,
    )


def _select_metric_sheets(
    sheets: list[DetectedSheet],
    *,
    selected_sheet: DetectedSheet,
    profile_options: dict[str, Any],
) -> tuple[DetectedSheet, DetectedSheet | None]:
    named_stats = _named_sheet(sheets, profile_options.get("stats_sheet_name"))
    named_association = _named_sheet(sheets, profile_options.get("association_sheet_name"))
    if named_stats is not None:
        return named_stats, named_association

    candidates = [sheet for sheet in sheets if _is_metric_candidate(sheet)]
    if len(candidates) < 2:
        return selected_sheet, None

    association_sheet = max(
        candidates,
        key=lambda sheet: (
            _sheet_year(sheet) is not None,
            _sheet_year(sheet) or -1,
            sheet.sheet_index,
            -_stats_field_count(sheet),
        ),
    )

    remaining = [sheet for sheet in candidates if sheet.sheet_name != association_sheet.sheet_name]
    same_or_previous_year = [
        sheet
        for sheet in remaining
        if _sheet_year(sheet) is not None
        and _sheet_year(association_sheet) is not None
        and (_sheet_year(sheet) or -1) <= (_sheet_year(association_sheet) or -1)
    ]
    if same_or_previous_year:
        stats_sheet = max(
            same_or_previous_year,
            key=lambda sheet: (
                _sheet_year(sheet) or -1,
                _stats_field_count(sheet),
                -sheet.sheet_index,
            ),
        )
    else:
        earlier_sheets = [sheet for sheet in remaining if sheet.sheet_index < association_sheet.sheet_index]
        pool = earlier_sheets or remaining
        stats_sheet = max(
            pool,
            key=lambda sheet: (
                _stats_field_count(sheet),
                _sheet_year(sheet) or -1,
                -sheet.sheet_index,
            ),
        )
    return stats_sheet, association_sheet


def _build_association_lookup(
    association_sheet: DetectedSheet,
    *,
    join_strategy: str,
    issues: list[ValidationIssue],
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in association_sheet.records:
        if not _association_row_is_usable(association_sheet, row):
            continue
        join_value = _row_join_value(association_sheet, row, join_strategy)
        if not join_value:
            continue
        if join_value in lookup:
            duplicates.add(join_value)
            continue
        lookup[join_value] = row
    for duplicate in sorted(duplicates):
        lookup.pop(duplicate, None)
        issues.append(
            ValidationIssue(
                code="season_merge_ambiguous_player",
                message=(
                    f"Duplicate {join_strategy} match {duplicate!r} found on "
                    f"{association_sheet.sheet_name}; skipped ambiguous roster mapping."
                ),
                severity=ValidationSeverity.WARNING,
                details={
                    "join_strategy": join_strategy,
                    "join_value": duplicate,
                    "association_sheet": association_sheet.sheet_name,
                },
            )
        )
    return lookup


def _row_join_value(sheet: DetectedSheet, row: dict[str, Any], join_strategy: str) -> str:
    if join_strategy == "player_id":
        column = _resolve_column(sheet, "player_id")
        if column:
            raw_value = str(row.get(column, "")).strip()
            if raw_value:
                return raw_value
    column = _resolve_column(sheet, "player_name")
    return _normalize_name(str(row.get(column, "")).strip()) if column else ""


def _is_metric_candidate(sheet: DetectedSheet) -> bool:
    fields = set(sheet.field_mappings)
    return bool({"team"} & fields) and bool({"player_name", "player_id"} & fields)


def _stats_field_count(sheet: DetectedSheet) -> int:
    return len([field for field in sheet.field_mappings if field not in _IDENTITY_FIELDS and field != "event_id"])


def _sheet_year(sheet: DetectedSheet) -> int | None:
    match = re.search(r"\b(20\d{2})\b", sheet.sheet_name)
    return int(match.group(1)) if match else None


def _named_sheet(sheets: Iterable[DetectedSheet], sheet_name: Any) -> DetectedSheet | None:
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        return None
    for sheet in sheets:
        if sheet.sheet_name == sheet_name:
            return sheet
    return None


def _resolve_column(sheet: DetectedSheet, field_name: str) -> str | None:
    return sheet.field_mappings.get(field_name)


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _association_row_is_usable(sheet: DetectedSheet, row: dict[str, Any]) -> bool:
    player_column = _resolve_column(sheet, "player_name")
    if player_column:
        player_name = str(row.get(player_column, "")).strip()
        if not player_name or player_name == "Player":
            return False
    team_column = _resolve_column(sheet, "team")
    if team_column:
        team = str(row.get(team_column, "")).strip()
        if not team or team in {"2TM", "Team"}:
            return False
    return True


__all__ = [
    "MergedSeasonRow",
    "SeasonMergeResult",
    "infer_merge_profile_options",
    "merge_metric_detection",
]
