"""Vercel Blob write-through cache for the writable data tree."""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

from core.data_layout import REPO_ROOT, get_writable_root

logger = logging.getLogger(__name__)

BLOB_PREFIX = "serinn-labs"

_client: object | None = None


def blob_enabled() -> bool:
    """Return True when Blob credentials are available."""

    if os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip():
        return True
    if os.environ.get("VERCEL") and os.environ.get("VERCEL_OIDC_TOKEN", "").strip():
        return True
    return False


def blob_should_sync() -> bool:
    """Blob sync applies only on the writable tree (Vercel / ``SERINN_WRITABLE_ROOT``)."""

    from core.data_layout import uses_writable_data_tree

    return blob_enabled() and uses_writable_data_tree()


def normalize_rel_path(rel_path: str) -> str:
    """Normalize *rel_path* relative to the writable root; reject traversal."""

    normalized = rel_path.replace("\\", "/").strip().lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        raise ValueError(f"Invalid relative path: {rel_path!r}")
    return normalized


def blob_key_for(rel_path: str) -> str:
    return f"{BLOB_PREFIX}/{normalize_rel_path(rel_path)}"


def rel_path_from_blob_key(blob_key: str) -> str | None:
    prefix = f"{BLOB_PREFIX}/"
    if not blob_key.startswith(prefix):
        return None
    rel = blob_key[len(prefix) :]
    if not rel or ".." in rel.split("/"):
        return None
    return rel


def _get_client():
    global _client
    if _client is None:
        from vercel.blob import BlobClient

        _client = BlobClient()
    return _client


def _local_path(rel_path: str) -> Path:
    return get_writable_root() / normalize_rel_path(rel_path)


def _guess_content_type(path: Path) -> str | None:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed


def _blob_exists(blob_key: str) -> bool:
    try:
        _get_client().head(blob_key)
        return True
    except Exception:
        return False


def materialize(rel_path: str) -> Path | None:
    """Download *rel_path* from Blob into the local cache when missing locally."""

    if not blob_should_sync():
        local = _local_path(rel_path)
        return local if local.is_file() else None

    rel = normalize_rel_path(rel_path)
    local = _local_path(rel)
    if local.is_file():
        return local

    blob_key = blob_key_for(rel)
    if not _blob_exists(blob_key):
        return None

    try:
        _get_client().download_file(
            blob_key,
            local,
            access="private",
            overwrite=True,
            create_parents=True,
        )
    except Exception as exc:
        logger.warning("Blob materialize failed for %s: %s", rel, exc)
        return local if local.is_file() else None

    return local if local.is_file() else None


def persist(rel_path: str) -> None:
    """Upload a local cached file to Blob."""

    if not blob_should_sync():
        return

    rel = normalize_rel_path(rel_path)
    local = _local_path(rel)
    if not local.is_file():
        return

    try:
        _get_client().upload_file(
            local,
            blob_key_for(rel),
            access="private",
            overwrite=True,
            content_type=_guess_content_type(local),
            multipart=local.stat().st_size > 5 * 1024 * 1024,
        )
    except Exception as exc:
        logger.warning("Blob persist failed for %s: %s", rel, exc)


def delete_blob(rel_path: str) -> None:
    """Remove *rel_path* from Blob (local delete is caller's responsibility)."""

    if not blob_should_sync():
        return

    blob_key = blob_key_for(rel_path)
    try:
        _get_client().delete(blob_key)
    except Exception as exc:
        logger.warning("Blob delete failed for %s: %s", rel_path, exc)


def persist_path(path: Path) -> None:
    """Upload *path* when it lives under the writable root."""

    if not blob_should_sync():
        return
    try:
        rel = path.resolve().relative_to(get_writable_root().resolve())
    except ValueError:
        return
    persist(str(rel).replace("\\", "/"))


def delete_path(path: Path) -> None:
    """Delete *path* from Blob when it lives under the writable root."""

    if not blob_should_sync():
        return
    try:
        rel = path.resolve().relative_to(get_writable_root().resolve())
    except ValueError:
        return
    delete_blob(str(rel).replace("\\", "/"))


def materialize_tree(prefix: str = "") -> None:
    """Download all blobs under *prefix* into the local cache."""

    if not blob_should_sync():
        return

    rel_prefix = normalize_rel_path(prefix) if prefix.strip() else ""
    blob_prefix = blob_key_for(rel_prefix) if rel_prefix else BLOB_PREFIX
    if rel_prefix and not blob_prefix.endswith("/"):
        blob_prefix = f"{blob_prefix}/"

    client = _get_client()
    cursor: str | None = None
    while True:
        result = client.list_objects(prefix=blob_prefix, cursor=cursor)
        for item in result.blobs:
            rel = rel_path_from_blob_key(item.pathname)
            if rel:
                materialize(rel)
        if not result.has_more:
            break
        cursor = result.cursor


def _repo_seed_files() -> list[Path]:
    paths: list[Path] = []
    for rel in (
        "config/settings.yaml",
        "config/topic_import_ids_catalog.json",
    ):
        path = REPO_ROOT / rel
        if path.is_file():
            paths.append(path)

    prof_dir = REPO_ROOT / "config" / "input_profiles"
    if prof_dir.is_dir():
        paths.extend(p for p in sorted(prof_dir.rglob("*")) if p.is_file())
    return paths


def _upload_repo_file(repo_path: Path, *, overwrite: bool) -> None:
    rel = str(repo_path.relative_to(REPO_ROOT)).replace("\\", "/")
    _get_client().upload_file(
        repo_path,
        blob_key_for(rel),
        access="private",
        overwrite=overwrite,
        content_type=_guess_content_type(repo_path),
    )


def _merge_repo_inputs_files_into_local_settings() -> bool:
    """Add bundled ``inputs.files`` packages missing from writable settings."""

    import yaml

    repo_settings = REPO_ROOT / "config" / "settings.yaml"
    local_settings = _local_path("config/settings.yaml")
    if not repo_settings.is_file() or not local_settings.is_file():
        return False

    with repo_settings.open(encoding="utf-8") as fh:
        repo_data = yaml.safe_load(fh) or {}
    with local_settings.open(encoding="utf-8") as fh:
        local_data = yaml.safe_load(fh) or {}

    repo_files = ((repo_data.get("inputs") or {}).get("files") or {})
    local_inputs = dict(local_data.get("inputs") or {})
    local_files = dict(local_inputs.get("files") or {})
    if not isinstance(repo_files, dict):
        return False

    changed = False
    for key, slots in repo_files.items():
        if key not in local_files and isinstance(slots, dict):
            local_files[key] = slots
            changed = True

    if not changed:
        return False

    local_inputs["files"] = local_files
    local_data["inputs"] = local_inputs
    with local_settings.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            local_data,
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    return True


def seed_blob_from_repo_if_empty() -> None:
    """Seed Blob from bundled repo files when empty; merge new bundled packages."""

    if not blob_should_sync():
        return

    settings_key = blob_key_for("config/settings.yaml")
    if not _blob_exists(settings_key):
        for repo_path in _repo_seed_files():
            _upload_repo_file(repo_path, overwrite=False)
        return

    materialize("config/settings.yaml")
    if _merge_repo_inputs_files_into_local_settings():
        persist("config/settings.yaml")


def sync_blob_on_bootstrap() -> None:
    """Seed Blob when needed and hydrate the config subtree into ``/tmp``."""

    if not blob_should_sync():
        return
    seed_blob_from_repo_if_empty()
    materialize_tree("config")
