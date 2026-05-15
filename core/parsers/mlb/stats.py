"""MLB player stats parsing and ranking helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..base import InputParser
from ..contracts import ParserResult, PlayerStatRecord, SourceRole, ValidationIssue, ValidationSeverity
from ..detector import inspect_file
from ..season_merge import merge_metric_detection
from ..validators import validate_required_fields
from .common import TEAM_MAP, normalize_team_name

_STAT_FIELD_MAP = {
    "HR": "hr",
    "RBI": "rbi",
    "SB": "sb",
    "WAR": "war",
}


class MlbStatsParser(InputParser):
    """Parse MLB hitter stats into canonical player records."""

    def __init__(self, category_key: str = "mlb") -> None:
        super().__init__()
        self.category_key = category_key
        self._detection = None
        self._normalized: list[PlayerStatRecord] = []

    def load(self, filepath: str | Path) -> "MlbStatsParser":
        self._loaded_path = Path(filepath)
        self._detection = inspect_file(
            self._loaded_path,
            category_key=self.category_key,
            preferred_role=SourceRole.METRIC_SOURCE,
            preferred_sheet_terms=("2026",),
        )
        return self

    def normalize(self) -> ParserResult:
        if self._detection is None:
            raise RuntimeError("Stats parser must load a file before normalize().")

        detected = self._detection.detected_file
        merge_result = merge_metric_detection(self._detection)
        issues = list(self._detection.issues)
        issues.extend(merge_result.issues)
        issues.extend(
            _validate_stats_merge(
                file_path=str(detected.file_path),
                source_role=detected.source_role,
                merge_result=merge_result,
            )
        )

        errors = [issue for issue in issues if issue.severity == ValidationSeverity.ERROR]
        warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]
        if errors:
            return ParserResult(
                data=[],
                warnings=warnings,
                errors=errors,
                profile_used=detected.profile_used,
            )

        stats_sheet = merge_result.stats_sheet
        association_sheet = merge_result.association_sheet or merge_result.stats_sheet
        team_column = association_sheet.field_mappings["team"]
        player_column = (
            association_sheet.field_mappings.get("player_name")
            or stats_sheet.field_mappings["player_name"]
        )
        stat_columns = {
            stat_name: stats_sheet.field_mappings[field_name]
            for stat_name, field_name in _STAT_FIELD_MAP.items()
            if field_name in stats_sheet.field_mappings
        }
        source_sheet = _source_sheet_label(merge_result)

        normalized: list[PlayerStatRecord] = []
        for row_number, merged_row in enumerate(
            merge_result.merged_rows,
            start=stats_sheet.header_row_index + 2,
        ):
            stats_row = merged_row.stats_row
            player_row = merged_row.association_row or stats_row
            player_name = str(player_row.get(player_column, "")).strip()
            source_team = str(player_row.get(team_column, "")).strip()
            if not player_name or player_name == "Player":
                continue
            if not source_team or source_team in {"2TM", "Team"}:
                continue
            team = normalize_team_name(source_team)
            stat_values = {
                stat_name: _coerce_float(stats_row.get(column_name, 0))
                for stat_name, column_name in stat_columns.items()
            }
            normalized.append(
                PlayerStatRecord(
                    player_name=player_name,
                    team=team,
                    source_team=source_team,
                    stat_values=stat_values,
                    source_sheet=source_sheet,
                    row_number=row_number,
                )
            )

        self._normalized = normalized
        return ParserResult(
            data=normalized,
            warnings=warnings,
            errors=[],
            profile_used=detected.profile_used,
        )

    def get_top_players(self, team: str, stat: str, n: int) -> list[PlayerStatRecord]:
        """Return top N players for a given team/stat from normalized stats."""

        normalized_team = normalize_team_name(team)
        stat_key = stat.upper()
        return sorted(
            [record for record in self._normalized if record.team == normalized_team],
            key=lambda record: (-record.stat_values.get(stat_key, 0.0), record.player_name),
        )[:n]


def _coerce_float(value: Any) -> float:
    if value in ("", None):
        return 0.0
    try:
        return float(pd.to_numeric(value))
    except (TypeError, ValueError):
        return 0.0


def _validate_stats_merge(
    *,
    file_path: str,
    source_role: SourceRole,
    merge_result,
) -> list[ValidationIssue]:
    issues = validate_required_fields(
        file_path=file_path,
        source_role=source_role,
        field_mappings=merge_result.stats_sheet.field_mappings,
        required_fields=["player_name", "team", "hr", "rbi", "sb"],
    )
    if merge_result.association_sheet is not None:
        issues.extend(
            validate_required_fields(
                file_path=file_path,
                source_role=source_role,
                field_mappings=merge_result.association_sheet.field_mappings,
                required_fields=["team"],
            )
        )
        if "player_name" not in merge_result.association_sheet.field_mappings and (
            "player_name" not in merge_result.stats_sheet.field_mappings
        ):
            issues.append(
                ValidationIssue(
                    code="missing_required_field",
                    message="Missing required field 'player_name'.",
                    severity=ValidationSeverity.ERROR,
                    file_path=file_path,
                    source_role=source_role,
                    field_name="player_name",
                )
            )
    return issues


def _source_sheet_label(merge_result) -> str | None:
    if merge_result.association_sheet is None:
        return merge_result.stats_sheet.sheet_name
    return (
        f"{merge_result.stats_sheet.sheet_name}"
        f" -> {merge_result.association_sheet.sheet_name}"
    )


__all__ = ["MlbStatsParser", "TEAM_MAP", "normalize_team_name"]

