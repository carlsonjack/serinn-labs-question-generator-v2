"""Shared schedule-row helpers for field-sport normalizers (golf, F1)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .package_options import placeholder_teams


def _cell(row: Mapping[str, Any], column: str | None) -> str:
    if not column:
        return ""
    return str(row.get(column, "")).strip()


def _slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")
    return slug or "event"


def resolve_field_event_teams(
    row: Mapping[str, Any],
    field_mappings: Mapping[str, str],
    settings: Mapping[str, Any],
    category_key: str,
) -> tuple[str, str]:
    """Use schedule home/away when both are present; otherwise package placeholders."""

    home = _cell(row, field_mappings.get("home_team"))
    away = _cell(row, field_mappings.get("away_team"))
    if home and away:
        return home, away
    return placeholder_teams(settings, category_key)


def resolve_field_event_id(
    row: Mapping[str, Any],
    field_mappings: Mapping[str, str],
    *,
    fallback: str,
) -> str:
    """Prefer mapped event_id column; otherwise use caller-supplied fallback slug."""

    mapped = _cell(row, field_mappings.get("event_id"))
    if mapped:
        return _slug(mapped)
    return fallback
