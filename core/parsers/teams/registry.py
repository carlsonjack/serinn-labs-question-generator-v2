"""Load per-league team alias tables from ``config/team_aliases/*.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.template_ui import normalize_template_package

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALIASES_DIR = _REPO_ROOT / "config" / "team_aliases"


def _aliases_dir() -> Path:
    from core.data_layout import bootstrap_if_needed, get_writable_root, uses_writable_data_tree

    bootstrap_if_needed()
    if uses_writable_data_tree():
        path = get_writable_root() / "config" / "team_aliases"
        if path.is_dir():
            return path
    return _ALIASES_DIR


def _flatten_teams(raw: dict[str, Any]) -> dict[str, str]:
    """Build alias → canonical code map; detect conflicts."""

    flat: dict[str, str] = {}
    teams = raw.get("teams") or []
    if not isinstance(teams, list):
        raise ValueError("teams must be a list")
    for entry in teams:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if not code:
            raise ValueError("each team entry requires a non-empty code")
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError(f"aliases for {code!r} must be a list")
        for alias in aliases:
            label = str(alias).strip()
            if not label:
                continue
            if label in flat and flat[label] != code:
                raise ValueError(
                    f"Duplicate alias {label!r} maps to both {flat[label]!r} and {code!r}"
                )
            flat[label] = code
        if code not in flat:
            flat[code] = code
    return flat


def _load_yaml_file(path: Path) -> tuple[str, dict[str, str], list[str]]:
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid team aliases file: {path}")
    package_key = str(raw.get("package_key") or path.stem).strip()
    norm_key = normalize_template_package(package_key)
    flat = _flatten_teams(raw)
    extra_keys: list[str] = []
    for alias in raw.get("package_aliases") or []:
        extra = normalize_template_package(str(alias))
        if extra and extra != norm_key:
            extra_keys.append(extra)
    return norm_key, flat, extra_keys


@lru_cache(maxsize=1)
def _load_all_maps() -> dict[str, dict[str, str]]:
    """Load every ``*.yaml`` in the team aliases directory."""

    root = _aliases_dir()
    if not root.is_dir():
        return {}
    combined: dict[str, dict[str, str]] = {}
    for path in sorted(root.glob("*.yaml")):
        norm_key, flat, extra_keys = _load_yaml_file(path)
        combined[norm_key] = flat
        for extra in extra_keys:
            combined[extra] = flat
    return combined


def get_flat_map(package_key: str) -> dict[str, str] | None:
    """Return alias → code map for *package_key*, or None if unknown."""

    key = normalize_template_package(package_key)
    if not key:
        return None
    return _load_all_maps().get(key)


def list_registered_packages() -> list[str]:
    """Return sorted normalized package keys with alias maps."""

    return sorted(_load_all_maps().keys())


def reload_team_aliases() -> None:
    """Clear cached maps (for tests)."""

    _load_all_maps.cache_clear()
