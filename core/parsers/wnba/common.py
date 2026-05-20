"""WNBA team labels (schedule) ↔ stats workbook ``TEAM`` codes."""

from __future__ import annotations

from core.parsers.teams.registry import get_flat_map

TEAM_MAP: dict[str, str] = get_flat_map("wnba") or {}


def normalize_team_name(team_name: str) -> str:
    """Map a schedule or stats team label to the stats ``TEAM`` code."""

    normalized = team_name.strip()
    return TEAM_MAP.get(normalized, normalized)
