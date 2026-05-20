"""Resolve configured input file slots from settings (category-agnostic UI + pipeline)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

_PKG_OR_SLOT_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")

INPUT_DATA_SUFFIXES: frozenset[str] = frozenset({".xlsx", ".csv"})


def resolve_input_upload_filename(configured_name: str, uploaded_filename: str) -> str | None:
    """Return the on-disk basename for an uploaded slot file (extension from upload)."""

    suffix = Path(uploaded_filename).suffix.lower()
    if suffix not in INPUT_DATA_SUFFIXES:
        return None
    safe = _safe_target_filename(configured_name)
    if not safe:
        return None
    return Path(safe).stem + suffix


def _safe_target_filename(name: str) -> str | None:
    s = name.strip()
    if not s or ".." in s or "/" in s or "\\" in s:
        return None
    if Path(s).name != s:
        return None
    return s


def normalize_inputs_files(raw: Any) -> dict[str, dict[str, str]]:
    """Validate and normalize the ``inputs.files`` mapping from UI or API JSON.

    *Package* and *slot* ids must match ``^[a-zA-Z][a-zA-Z0-9_]{0,63}$``.
    Target names must be single path components (basename only), non-empty.
    """

    if not isinstance(raw, dict):
        raise ValueError("inputs.files must be a JSON object (package → slots).")
    out: dict[str, dict[str, str]] = {}
    for pkg_key, slots in raw.items():
        if not isinstance(pkg_key, str) or not _PKG_OR_SLOT_ID.fullmatch(pkg_key):
            raise ValueError(
                f"Invalid input package key: {pkg_key!r} "
                "(use letters, digits, underscore; start with a letter)."
            )
        if not isinstance(slots, dict):
            raise ValueError(f"Package {pkg_key!r} must map slot ids to filenames.")
        slot_map: dict[str, str] = {}
        for sid, fname in slots.items():
            if not isinstance(sid, str) or not _PKG_OR_SLOT_ID.fullmatch(sid):
                raise ValueError(
                    f"Invalid slot id {sid!r} under {pkg_key!r} "
                    "(use letters, digits, underscore; start with a letter)."
                )
            if not isinstance(fname, str):
                raise ValueError(f"Filename for {pkg_key}.{sid} must be a string.")
            safe = _safe_target_filename(fname)
            if not safe:
                raise ValueError(
                    f"Invalid filename for {pkg_key}.{sid}: {fname!r} "
                    "(use a single file name, no paths)."
                )
            slot_map[sid] = safe
        if not slot_map:
            raise ValueError(f"Package {pkg_key!r} must define at least one slot.")
        out[pkg_key] = slot_map
    if not out:
        raise ValueError("Define at least one input package with at least one slot.")
    return out


def _humanize_slot_id(slot_id: str) -> str:
    s = slot_id.replace("_", " ").strip()
    if not s:
        return slot_id
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()


def get_inputs_category_key(settings: Mapping[str, Any]) -> str:
    """Which key under ``inputs.files`` to use (e.g. ``mlb``, ``markets``)."""

    inputs = settings.get("inputs") or {}
    raw = inputs.get("category_key")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    files = inputs.get("files") or {}
    if isinstance(files, dict) and files:
        return next(iter(sorted(files.keys())))
    return "mlb"


def present_files_map(
    input_dir: Path, files_map: Mapping[str, str]
) -> dict[str, str]:
    """Return configured slots whose target file exists on disk."""

    return {
        slot_id: target_name
        for slot_id, target_name in files_map.items()
        if (input_dir / target_name).is_file()
    }


def require_present_input_files(
    input_dir: Path, files_map: Mapping[str, str]
) -> str | None:
    """Return an error message when no configured input files are present."""

    if present_files_map(input_dir, files_map):
        return None
    if not files_map:
        return "No input files configured for this package."
    names = ", ".join(sorted(files_map.values()))
    return f"No uploaded input files found. Expected at least one of: {names}"


def get_files_map_for_category(
    settings: Mapping[str, Any], category_key: str | None = None
) -> dict[str, str]:
    """Map slot id -> target filename for *category_key*."""

    inputs = settings.get("inputs") or {}
    files_root = inputs.get("files") or {}
    if not isinstance(files_root, dict):
        return {}
    key = category_key if category_key is not None else get_inputs_category_key(settings)
    block = files_root.get(key)
    if not isinstance(block, dict):
        return {}
    out: dict[str, str] = {}
    for slot_id, name in block.items():
        if not isinstance(slot_id, str) or not isinstance(name, str):
            continue
        if not name.strip():
            continue
        out[slot_id] = name.strip()
    return out


def list_input_categories(settings: Mapping[str, Any]) -> list[str]:
    inputs = settings.get("inputs") or {}
    files_root = inputs.get("files") or {}
    if not isinstance(files_root, dict):
        return []
    return sorted(str(k) for k in files_root.keys())


def resolve_inputs_package_file_key(
    settings: Mapping[str, Any], category_key: str
) -> str | None:
    """Return the canonical ``inputs.files`` key for *category_key* (case-insensitive)."""

    files_root = (settings.get("inputs") or {}).get("files") or {}
    if not isinstance(files_root, dict):
        return None
    ck = category_key.strip()
    if ck in files_root and isinstance(files_root[ck], dict):
        return ck
    lower = ck.lower()
    for k, v in files_root.items():
        if isinstance(k, str) and isinstance(v, dict) and k.lower() == lower:
            return k
    return None


def clear_category_input_files(
    input_dir: Path,
    settings: Mapping[str, Any],
    category_key: str,
    *,
    only_slot_ids: set[str] | frozenset[str] | None = None,
    skip_slot_ids: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Remove on-disk files for configured slots of *category_key*.

    Returns basenames that were deleted. Missing files are ignored.
    """

    files_map = get_files_map_for_category(settings, category_key)
    removed: list[str] = []
    for slot_id, target_name in files_map.items():
        if only_slot_ids is not None and slot_id not in only_slot_ids:
            continue
        if skip_slot_ids is not None and slot_id in skip_slot_ids:
            continue
        path = input_dir / target_name
        if path.is_file():
            path.unlink()
            removed.append(target_name)
    return removed


def clear_unuploaded_category_input_files(
    input_dir: Path,
    files_map: Mapping[str, str],
    uploaded_slot_ids: set[str] | frozenset[str],
) -> list[str]:
    """Remove files for slots that were not part of an upload batch."""

    removed: list[str] = []
    for slot_id, target_name in files_map.items():
        if slot_id in uploaded_slot_ids:
            continue
        path = input_dir / target_name
        if path.is_file():
            path.unlink()
            removed.append(target_name)
    return removed


def iter_input_slots(
    settings: Mapping[str, Any], category_key: str | None = None
) -> list[dict[str, Any]]:
    """UI rows: ``slot_id``, ``label``, ``target_filename``."""

    key = category_key if category_key is not None else get_inputs_category_key(settings)
    files_map = get_files_map_for_category(settings, key)
    slots: list[dict[str, Any]] = []
    for slot_id in sorted(files_map.keys()):
        slots.append(
            {
                "slot_id": slot_id,
                "label": _humanize_slot_id(slot_id),
                "target_filename": files_map[slot_id],
                "category_key": key,
            }
        )
    return slots
