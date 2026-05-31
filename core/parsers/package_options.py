"""Package-level competition format and field-sport options."""

from __future__ import annotations

from typing import Any, Mapping

from core.template_ui import normalize_template_package

from .stat_keys import stat_storage_key

COMPETITION_FORMAT_TEAM = "team_sport"
COMPETITION_FORMAT_FIELD = "field"


def get_package_options(
    settings: Mapping[str, Any], category_key: str | None
) -> dict[str, Any]:
    pkgs = ((settings.get("inputs") or {}).get("packages")) or {}
    if not isinstance(pkgs, dict):
        return {}
    key = normalize_template_package(category_key or "")
    if not key:
        return {}
    direct = pkgs.get(key) or pkgs.get(key.upper()) or pkgs.get(key.capitalize())
    if isinstance(direct, dict):
        return dict(direct)
    for pkg_key, value in pkgs.items():
        if normalize_template_package(str(pkg_key)) == key and isinstance(value, dict):
            return dict(value)
    return {}


def competition_format(
    settings: Mapping[str, Any],
    category_key: str | None,
    *,
    spec_format: str | None = None,
) -> str:
    if spec_format in (COMPETITION_FORMAT_FIELD, COMPETITION_FORMAT_TEAM):
        return spec_format
    fmt = str(get_package_options(settings, category_key).get("competition_format") or "").strip().lower()
    if fmt == COMPETITION_FORMAT_FIELD:
        return COMPETITION_FORMAT_FIELD
    return COMPETITION_FORMAT_TEAM


def is_field_competition(
    settings: Mapping[str, Any],
    category_key: str | None,
    *,
    spec_format: str | None = None,
) -> bool:
    return competition_format(settings, category_key, spec_format=spec_format) == COMPETITION_FORMAT_FIELD


def field_team_code(settings: Mapping[str, Any], category_key: str | None) -> str:
    return str(get_package_options(settings, category_key).get("field_team_code") or "FIELD").strip()


def placeholder_teams(
    settings: Mapping[str, Any], category_key: str | None
) -> tuple[str, str]:
    opts = get_package_options(settings, category_key)
    home = str(opts.get("placeholder_home_team") or "Participant_A").strip()
    away = str(opts.get("placeholder_away_team") or "Participant_B").strip()
    return home, away


def ascending_stat_columns(
    settings: Mapping[str, Any], category_key: str | None
) -> frozenset[str]:
    raw = get_package_options(settings, category_key).get("ascending_stat_columns") or []
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    keys: set[str] = set()
    for column in raw:
        text = str(column).strip()
        if not text:
            continue
        keys.add(text.upper())
        keys.add(stat_storage_key(text))
    return frozenset(keys)


def skip_status_values(settings: Mapping[str, Any], category_key: str | None) -> frozenset[str]:
    raw = get_package_options(settings, category_key).get("skip_status_values") or []
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    return frozenset(str(v).strip().lower() for v in raw if str(v).strip())
