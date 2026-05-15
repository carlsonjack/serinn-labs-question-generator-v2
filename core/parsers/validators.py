"""Validation helpers for parser inputs and normalized bundles."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    NormalizedEvent,
    PlayerStatRecord,
    SourceRole,
    ValidationIssue,
    ValidationSeverity,
)


def validate_required_fields(
    *,
    file_path: str,
    source_role: SourceRole,
    field_mappings: dict[str, str],
    required_fields: Iterable[str],
) -> list[ValidationIssue]:
    """Check whether a detected file exposes required canonical fields."""

    issues: list[ValidationIssue] = []
    for field_name in required_fields:
        if field_name not in field_mappings:
            issues.append(
                ValidationIssue(
                    code="missing_required_field",
                    message=f"Missing required field '{field_name}'.",
                    severity=ValidationSeverity.ERROR,
                    file_path=file_path,
                    source_role=source_role,
                    field_name=field_name,
                )
            )
    return issues


def validate_date_filter_results(events: list[NormalizedEvent]) -> list[ValidationIssue]:
    """Warn when date filtering leaves no events to generate from."""

    if events:
        return []
    return [
        ValidationIssue(
            code="empty_date_window",
            message="Date filter produced zero events.",
            severity=ValidationSeverity.WARNING,
        )
    ]


def validate_schedule_teams_have_stats(
    events: list[NormalizedEvent],
    player_stats: list[PlayerStatRecord],
    *,
    team_lookup: dict[str, str],
) -> list[ValidationIssue]:
    """Warn if schedule teams have no matching player stats."""

    available_teams = {record.team for record in player_stats}
    issues: list[ValidationIssue] = []
    for event in events:
        for raw_team in (event.home_team, event.away_team):
            normalized_team = team_lookup.get(raw_team, raw_team)
            if normalized_team not in available_teams:
                issues.append(
                    ValidationIssue(
                        code="missing_team_stats",
                        message=f"No player stats found for team '{raw_team}'.",
                        severity=ValidationSeverity.WARNING,
                        details={"team": raw_team, "normalized_team": normalized_team},
                    )
                )
    return issues

