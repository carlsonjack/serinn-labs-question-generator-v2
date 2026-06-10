"""Load global settings from YAML with optional local overrides and env API key."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from core.data_layout import REPO_ROOT, bootstrap_if_needed, materialize_relative, persist_relative

# Tests may monkeypatch these to redirect settings I/O to temp files.
_SETTINGS_PATH_OVERRIDE: Path | None = None
_SETTINGS_LOCAL_PATH_OVERRIDE: Path | None = None


def _settings_path() -> Path:
    if _SETTINGS_PATH_OVERRIDE is not None:
        return _SETTINGS_PATH_OVERRIDE
    bootstrap_if_needed()
    return materialize_relative("config/settings.yaml")


def _settings_local_path() -> Path:
    if _SETTINGS_LOCAL_PATH_OVERRIDE is not None:
        return _SETTINGS_LOCAL_PATH_OVERRIDE
    bootstrap_if_needed()
    return materialize_relative("config/settings.local.yaml")


def _load_dotenv() -> None:
    """Populate ``os.environ`` from a repo-root ``.env`` if present (optional dep)."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = REPO_ROOT / ".env"
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
    settings_path = _settings_path()
    if not settings_path.is_file():
        raise FileNotFoundError(f"Missing config file: {settings_path}")

    with settings_path.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    local_path = _settings_local_path()
    if local_path.is_file():
        with local_path.open(encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        if isinstance(local, dict):
            data = _deep_merge(data, local)

    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        data["openai_api_key"] = env_key

    return data


def load_settings_disk_only() -> dict[str, Any]:
    """Load ``settings.yaml`` (+ optional ``settings.local.yaml``) without env API key."""

    settings_path = _settings_path()
    if not settings_path.is_file():
        raise FileNotFoundError(f"Missing config file: {settings_path}")

    with settings_path.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    local_path = _settings_local_path()
    if local_path.is_file():
        with local_path.open(encoding="utf-8") as f:
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

    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    persist_relative("config/settings.yaml")
