"""MLB-specific constants and helpers."""

from __future__ import annotations

from core.parsers.teams.registry import get_flat_map

TEAM_MAP: dict[str, str] = get_flat_map("mlb") or {}


def normalize_team_name(team_name: str) -> str:
    """Normalize MLB team labels to canonical abbreviations."""

    normalized = team_name.strip()
    return TEAM_MAP.get(normalized, normalized)
