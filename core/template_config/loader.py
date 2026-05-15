"""Load and validate question templates from a directory of JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import QuestionTemplate, parse_template_dict

_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DIR = _ROOT / "templates"


def index_template_json_paths_by_id(directory: Path) -> dict[str, list[Path]]:
    """Map template ``id`` to all JSON file paths that declare that id.

    Used to detect duplicate on-disk definitions (same ``id`` in multiple files).
    Invalid or non-object JSON files are skipped.
    """

    out: dict[str, list[Path]] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or "").strip()
        if not tid:
            continue
        out.setdefault(tid, []).append(path)
    return out


def load_template_dir(directory: Path | None = None) -> dict[str, QuestionTemplate]:
    """
    Load every *.json file in ``directory`` (default: repo ``templates/``).

    Returns a mapping of template ``id`` -> ``QuestionTemplate``.
    Raises if any file is invalid or duplicate ids appear.
    """

    base = directory if directory is not None else _DEFAULT_DIR
    if not base.is_dir():
        raise FileNotFoundError(f"Template directory not found: {base}")

    out: dict[str, QuestionTemplate] = {}
    for path in sorted(base.glob("*.json")):
        t = load_template_file(path)
        if t.id in out:
            raise ValueError(f"Duplicate template id {t.id!r} in {path} and earlier file")
        out[t.id] = t
    return out


def load_template_file(path: Path) -> QuestionTemplate:
    """Load a single JSON template file."""

    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Template root must be an object: {path}")
    return parse_template_dict(raw)


def default_templates_directory() -> Path:
    """Directory used when no path is passed to :func:`load_template_dir`."""

    return _DEFAULT_DIR


def resolve_templates_directory(settings: dict[str, Any]) -> Path:
    """
    Resolve ``templates_directory`` from :func:`core.config.load_settings` (repo-relative).

    Absolute paths are accepted as-is.
    """

    raw = settings.get("templates_directory", "templates")
    path = Path(str(raw))
    if path.is_absolute():
        return path
    return _ROOT / path
