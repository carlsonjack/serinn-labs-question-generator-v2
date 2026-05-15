"""Load global settings from YAML with optional local overrides and env API key."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS = _ROOT / "config" / "settings.yaml"
_SETTINGS_LOCAL = _ROOT / "config" / "settings.local.yaml"


def _load_dotenv() -> None:
    """Populate ``os.environ`` from a repo-root ``.env`` if present (optional dep)."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = _ROOT / ".env"
    if path.is_file():
        load_dotenv(path)


_load_dotenv()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge nested mapping values without discarding sibling keys."""

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings() -> dict[str, Any]:
    if not _SETTINGS.is_file():
        raise FileNotFoundError(f"Missing config file: {_SETTINGS}")

    with _SETTINGS.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    if _SETTINGS_LOCAL.is_file():
        with _SETTINGS_LOCAL.open(encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        if isinstance(local, dict):
            data = _deep_merge(data, local)

    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        data["openai_api_key"] = env_key

    return data


def load_settings_disk_only() -> dict[str, Any]:
    """Load ``settings.yaml`` (+ optional ``settings.local.yaml``) without env API key."""

    if not _SETTINGS.is_file():
        raise FileNotFoundError(f"Missing config file: {_SETTINGS}")

    with _SETTINGS.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    if _SETTINGS_LOCAL.is_file():
        with _SETTINGS_LOCAL.open(encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        if isinstance(local, dict):
            data = _deep_merge(data, local)

    return data


def save_settings_yaml(updates: dict[str, Any]) -> None:
    """Deep-merge *updates* into ``config/settings.yaml`` and write.

    Does not persist ``OPENAI_API_KEY`` from the environment — only values
    present in the YAML files plus *updates*. Empty string ``openai_api_key``
    in *updates* is ignored so an env-provided key is not wiped on save.

    If *updates* contains ``_inputs_files`` (a dict), it **replaces**
    ``inputs.files`` entirely after the merge (so removed packages/slots do not
    linger). The ``_inputs_files`` key is not written to YAML.
    """

    current = load_settings_disk_only()
    updates = dict(updates)
    inputs_files = updates.pop("_inputs_files", None)
    merged = _deep_merge(current, updates)
    if inputs_files is not None:
        ib = dict(merged.get("inputs") or {})
        ib["files"] = inputs_files
        merged["inputs"] = ib
    if updates.get("openai_api_key") in ("", None) and "openai_api_key" in updates:
        merged["openai_api_key"] = current.get("openai_api_key", "")

    _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with _SETTINGS.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
