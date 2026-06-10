"""Tests for :mod:`core.blob_store`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakeBlobItem:
    def __init__(self, pathname: str) -> None:
        self.pathname = pathname
        self.url = f"https://blob.example/{pathname}"


class _FakeListResult:
    def __init__(self, blobs: list[_FakeBlobItem], *, has_more: bool = False) -> None:
        self.blobs = blobs
        self.has_more = has_more
        self.cursor = None


@pytest.fixture
def blob_env(monkeypatch, tmp_path):
    writable = tmp_path / "writable"
    writable.mkdir()
    monkeypatch.setenv("SERINN_WRITABLE_ROOT", str(writable))
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")
    monkeypatch.delenv("VERCEL", raising=False)

    store: dict[str, bytes] = {}

    class FakeClient:
        def head(self, blob_key: str) -> None:
            if blob_key not in store:
                raise FileNotFoundError(blob_key)

        def upload_file(
            self,
            local_path,
            path,
            *,
            access="private",
            content_type=None,
            overwrite=False,
            multipart=False,
        ):
            data = Path(local_path).read_bytes()
            if path in store and not overwrite:
                raise FileExistsError(path)
            store[path] = data
            return MagicMock(pathname=path, url=f"https://blob/{path}")

        def put(self, path, body, **kwargs):
            store[path] = body if isinstance(body, bytes) else body.encode()
            return MagicMock(pathname=path)

        def download_file(
            self,
            url_or_path,
            local_path,
            *,
            access="private",
            overwrite=True,
            create_parents=True,
        ):
            key = url_or_path
            if key not in store:
                raise FileNotFoundError(key)
            dest = Path(local_path)
            if create_parents:
                dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(store[key])
            return str(dest)

        def delete(self, url_or_path) -> None:
            keys = url_or_path if isinstance(url_or_path, list) else [url_or_path]
            for key in keys:
                store.pop(key, None)

        def list_objects(self, *, prefix=None, cursor=None, limit=None, mode=None):
            matched = [
                _FakeBlobItem(k)
                for k in sorted(store)
                if prefix is None or k.startswith(prefix)
            ]
            return _FakeListResult(matched)

    fake = FakeClient()
    import core.blob_store as blob_store

    monkeypatch.setattr(blob_store, "_client", fake)
    return writable, store, fake


def test_blob_key_for_normalizes_paths() -> None:
    from core.blob_store import blob_key_for

    assert blob_key_for("config/settings.yaml") == "serinn-labs/config/settings.yaml"


def test_persist_and_materialize_round_trip(blob_env) -> None:
    writable, store, _fake = blob_env
    from core.blob_store import materialize, persist

    local = writable / "inputs" / "schedule.xlsx"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"excel-bytes")

    persist("inputs/schedule.xlsx")
    assert "serinn-labs/inputs/schedule.xlsx" in store

    local.unlink()
    restored = materialize("inputs/schedule.xlsx")
    assert restored is not None
    assert restored.read_bytes() == b"excel-bytes"


def test_delete_blob_removes_remote(blob_env) -> None:
    writable, store, _fake = blob_env
    from core.blob_store import delete_blob, persist

    local = writable / "outputs" / "out.csv"
    local.parent.mkdir(parents=True)
    local.write_text("a,b\n", encoding="utf-8")
    persist("outputs/out.csv")
    assert "serinn-labs/outputs/out.csv" in store

    delete_blob("outputs/out.csv")
    assert "serinn-labs/outputs/out.csv" not in store


def test_seed_blob_from_repo_if_empty_uploads_settings(blob_env, monkeypatch) -> None:
    writable, store, _fake = blob_env
    from core.blob_store import seed_blob_from_repo_if_empty
    from core.data_layout import REPO_ROOT

    repo_settings = REPO_ROOT / "config" / "settings.yaml"
    assert repo_settings.is_file()

    seed_blob_from_repo_if_empty()
    assert "serinn-labs/config/settings.yaml" in store
    assert store["serinn-labs/config/settings.yaml"] == repo_settings.read_bytes()


def test_merge_bundled_packages_into_existing_blob_settings(blob_env, monkeypatch) -> None:
    writable, store, fake = blob_env
    import yaml

    from core.blob_store import seed_blob_from_repo_if_empty
    from core.data_layout import REPO_ROOT

    minimal = {
        "inputs": {
            "files": {
                "mlb": {"event_source": "schedule.xlsx", "metric_source": "stats.xlsx"}
            }
        }
    }
    local_settings = writable / "config" / "settings.yaml"
    local_settings.parent.mkdir(parents=True)
    local_settings.write_text(yaml.safe_dump(minimal), encoding="utf-8")
    fake.upload_file(local_settings, "serinn-labs/config/settings.yaml", overwrite=True)

    repo_files = yaml.safe_load((REPO_ROOT / "config" / "settings.yaml").read_text())[
        "inputs"
    ]["files"]
    assert "ATP" in repo_files

    seed_blob_from_repo_if_empty()

    merged = yaml.safe_load(local_settings.read_text(encoding="utf-8"))
    assert "ATP" in merged["inputs"]["files"]
    assert "mlb" in merged["inputs"]["files"]


def test_save_settings_yaml_persists_to_blob(blob_env, monkeypatch, tmp_path) -> None:
    writable, store, _fake = blob_env
    from core.config import load_settings_disk_only, save_settings_yaml

    cfg = writable / "config"
    cfg.mkdir(parents=True)
    settings = cfg / "settings.yaml"
    settings.write_text("subcategory: MLB\n", encoding="utf-8")

    monkeypatch.setattr("core.config._SETTINGS_PATH_OVERRIDE", None)
    monkeypatch.setattr("core.config._SETTINGS_LOCAL_PATH_OVERRIDE", None)

    save_settings_yaml({"subcategory": "WNBA"})
    assert "serinn-labs/config/settings.yaml" in store
    disk = load_settings_disk_only()
    assert disk["subcategory"] == "WNBA"
