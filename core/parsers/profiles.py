"""Persistence helpers for inferred input profiles."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from .contracts import InputProfile, NormalizationSpec, SourceRole

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Default profile directory; tests monkeypatch this to a temp path. Ignored when
# :func:`core.data_layout.uses_writable_data_tree` is true (e.g. on Vercel).
_PROFILE_DIR = _REPO_ROOT / "config" / "input_profiles"
_NORMALIZER_PROFILE_DIRNAME = "normalizers"


def get_profile_dir() -> Path:
    """Return the profile directory, creating it lazily when needed."""

    from core.data_layout import bootstrap_if_needed, get_writable_root, uses_writable_data_tree

    bootstrap_if_needed()
    if uses_writable_data_tree():
        path = get_writable_root() / "config" / "input_profiles"
    else:
        path = _PROFILE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_normalizer_profile_dir() -> Path:
    """Return the declarative normalizer profile directory."""

    path = get_profile_dir() / _NORMALIZER_PROFILE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str) -> str:
    """Build stable human-readable filenames for saved profiles."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "profile"


def fingerprint_file(path: str | Path, chunk_size: int = 1_000_000) -> str:
    """Fingerprint the beginning of a source file for reproducibility."""

    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def profile_path(profile: InputProfile) -> Path:
    """Resolve the file path for a saved profile."""

    filename = (
        f"{slugify(profile.category_key)}"
        f"__{slugify(profile.source_role.value)}"
        f"__{slugify(profile.profile_name)}.yaml"
    )
    return get_profile_dir() / filename


def save_profile(profile: InputProfile) -> Path:
    """Persist one input profile to disk."""

    path = profile_path(profile)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(profile.to_dict(), handle, sort_keys=True)
    from core.data_layout import persist_path

    persist_path(path)
    return path


def normalization_spec_path(package_key: str) -> Path:
    """Resolve the declarative normalizer profile path for a package."""

    return get_normalizer_profile_dir() / f"{slugify(package_key)}.yaml"


def save_normalization_spec(spec: NormalizationSpec) -> Path:
    """Persist an approved declarative normalizer profile."""

    path = normalization_spec_path(spec.package_key)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(spec.to_dict(), handle, sort_keys=False)
    from core.data_layout import persist_path

    persist_path(path)
    return path


def load_normalization_spec(package_key: str) -> NormalizationSpec | None:
    """Load an approved declarative normalizer profile for *package_key*."""

    path = normalization_spec_path(package_key)
    if not path.is_file():
        from core.data_layout import get_writable_root, materialize_relative

        try:
            rel = path.resolve().relative_to(get_writable_root().resolve())
            materialize_relative(str(rel).replace("\\", "/"))
        except ValueError:
            pass
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid normalization spec: {path}")
    return NormalizationSpec.from_dict(raw)


def load_profiles(category_key: str | None = None) -> list[InputProfile]:
    """Load saved profiles, optionally filtered by category."""

    profiles: list[InputProfile] = []
    for path in sorted(get_profile_dir().glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        profile = InputProfile.from_dict(raw)
        if category_key and profile.category_key.lower() != category_key.lower():
            continue
        profiles.append(profile)
    return profiles


def match_profile(
    path: str | Path,
    *,
    category_key: str,
    source_role: SourceRole | None = None,
) -> InputProfile | None:
    """Match a saved profile by category, role, and file pattern."""

    file_path = Path(path)
    file_name = file_path.name
    file_fingerprint = fingerprint_file(file_path)
    for profile in load_profiles(category_key):
        if source_role and profile.source_role != source_role:
            continue
        matches_pattern = file_name == profile.file_pattern or file_path.match(
            profile.file_pattern
        )
        matches_fingerprint = (
            profile.fingerprint is None or profile.fingerprint == file_fingerprint
        )
        if matches_pattern and matches_fingerprint:
            return profile
    return None

