"""Resolve schedule team labels to stats workbook TEAM codes."""

from __future__ import annotations

from core.template_ui import normalize_template_package

from .registry import _load_all_maps, get_flat_map


def resolve_stats_team_code(team_label: str, category_key: str | None = None) -> str:
    """Return the team code used on ``PlayerStatRecord.team`` for *team_label*.

    *team_label* is usually ``NormalizedEvent.home_team`` / ``away_team`` (full name
    from the schedule). For packages without a registered map, the label is returned
    unchanged (trimmed).
    """

    label = (team_label or "").strip()
    if not label:
        return ""
    key = normalize_template_package(category_key or "")
    if not key:
        return label
    team_map = _load_all_maps().get(key)
    if team_map is None:
        return label
    return team_map.get(label, label)


def normalize_team_name(team_name: str, category_key: str | None = None) -> str:
    """Alias for :func:`resolve_stats_team_code` (sport-agnostic name)."""

    return resolve_stats_team_code(team_name, category_key)
