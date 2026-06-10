"""Topic import ID catalog for the UI (config/topic_import_ids_catalog.json)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Tests may monkeypatch to redirect catalog I/O.
_CATALOG_PATH_OVERRIDE: Path | None = None

_TOPIC_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}$")


def default_topic_import_catalog_path() -> Path:
    if _CATALOG_PATH_OVERRIDE is not None:
        return _CATALOG_PATH_OVERRIDE
    from core.data_layout import bootstrap_if_needed, materialize_relative

    bootstrap_if_needed()
    return materialize_relative("config/topic_import_ids_catalog.json")


def _normalize_catalog_items(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            topic_id = item.strip()
            label = ""
        elif isinstance(item, dict):
            topic_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
        else:
            continue
        if topic_id:
            entries.append({"id": topic_id, "label": label})
    return entries


def load_topic_import_ids_catalog(
    path: Path | None = None,
) -> list[dict[str, str]]:
    """Load searchable topic import ID suggestions. Returns [] if missing or invalid."""

    target = path or default_topic_import_catalog_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _normalize_catalog_items(raw)


def validate_topic_import_id_for_catalog(topic_id: str) -> str:
    """Return stripped id or raise ValueError."""

    tid = topic_id.strip()
    if not tid:
        raise ValueError("topic_import_id is empty.")
    if not _TOPIC_ID_PATTERN.fullmatch(tid):
        raise ValueError(
            "topic_import_id must be 1–200 characters: letters, digits, hyphen, underscore, or dot; "
            "must start with a letter or digit."
        )
    return tid


def append_topic_import_id_to_catalog(
    topic_id: str,
    *,
    label: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Append *topic_id* to the catalog JSON if not already present (case-insensitive).

    Returns a dict suitable for JSON: ok, added, already_exists, id, total.
    """

    target = path or default_topic_import_catalog_path()
    tid = validate_topic_import_id_for_catalog(topic_id)
    lab = (label or "").strip()

    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Cannot update catalog: {target.name} is not valid JSON. "
                "Fix the file manually, then try again."
            ) from exc
        entries = _normalize_catalog_items(raw)
    else:
        entries = []

    lower = tid.lower()
    for existing in entries:
        if existing["id"].lower() == lower:
            return {
                "ok": True,
                "added": False,
                "already_exists": True,
                "id": existing["id"],
                "total": len(entries),
            }

    entries.append({"id": tid, "label": lab})
    entries.sort(key=lambda e: e["id"].lower())

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(entries, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    from core.data_layout import persist_relative

    persist_relative("config/topic_import_ids_catalog.json")
    return {
        "ok": True,
        "added": True,
        "already_exists": False,
        "id": tid,
        "total": len(entries),
    }
