"""Repo vs writable layout for serverless (e.g. Vercel).

The deployed project tree is read-only except ``/tmp``. When ``VERCEL`` is set
(or ``SERINN_WRITABLE_ROOT`` is set to a directory), mutable paths
(settings, inputs, outputs, templates copy, profile YAML) live under a writable
root so uploads and saves do not raise OSError.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_writable_root() -> Path:
    """Directory for settings, inputs, outputs, and copied config/templates."""

    override = os.environ.get("SERINN_WRITABLE_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    if os.environ.get("VERCEL"):
        base = Path(os.environ.get("TMPDIR", "/tmp")) / "serinn-labs-data"
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()
    return REPO_ROOT


def uses_writable_data_tree() -> bool:
    return get_writable_root().resolve() != REPO_ROOT.resolve()


def resolve_inputs_directory(settings: Mapping[str, Any]) -> Path:
    """Resolve ``inputs.directory`` against the repo or writable root (Vercel / ``/tmp``)."""

    block = settings.get("inputs")
    if not isinstance(block, dict):
        block = {}
    raw = Path(str(block.get("directory", "inputs")))
    if raw.is_absolute():
        return raw
    bootstrap_if_needed()
    base = get_writable_root() if uses_writable_data_tree() else REPO_ROOT
    return base / raw


def bootstrap_if_needed() -> None:
    """Seed writable tree from the repo bundle (once per writable root)."""

    if not uses_writable_data_tree():
        return

    w = get_writable_root()
    sentinel = w / ".serinn_bootstrap_v1"
    if sentinel.is_file():
        return

    (w / "inputs").mkdir(parents=True, exist_ok=True)
    (w / "outputs").mkdir(parents=True, exist_ok=True)
    cfg = w / "config"
    cfg.mkdir(parents=True, exist_ok=True)

    src_settings = REPO_ROOT / "config" / "settings.yaml"
    dst_settings = cfg / "settings.yaml"
    if src_settings.is_file() and not dst_settings.is_file():
        shutil.copy2(src_settings, dst_settings)

    src_prof = REPO_ROOT / "config" / "input_profiles"
    dst_prof = cfg / "input_profiles"
    if src_prof.is_dir():
        shutil.copytree(src_prof, dst_prof, dirs_exist_ok=True)

    bundled_cat = REPO_ROOT / "config" / "topic_import_ids_catalog.json"
    dst_cat = cfg / "topic_import_ids_catalog.json"
    if bundled_cat.is_file() and not dst_cat.is_file():
        shutil.copy2(bundled_cat, dst_cat)

    src_tmpl = REPO_ROOT / "templates"
    dst_tmpl = w / "templates"
    if src_tmpl.is_dir():
        shutil.copytree(src_tmpl, dst_tmpl, dirs_exist_ok=True)

    sentinel.write_text("ok\n", encoding="utf-8")
