"""Tests for :mod:`core.data_layout` (Vercel / writable tree)."""

from __future__ import annotations

import io

import pandas as pd
import pytest


def test_get_writable_root_uses_tmp_under_vercel(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    from core.data_layout import get_writable_root

    root = get_writable_root()
    assert root == (tmp_path / "serinn-labs-data").resolve()


def test_resolve_inputs_directory_under_vercel(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    from core.data_layout import bootstrap_if_needed, resolve_inputs_directory

    bootstrap_if_needed()
    settings = {"inputs": {"directory": "inputs", "files": {"movies": {}}}}
    p = resolve_inputs_directory(settings)
    assert p == (tmp_path / "serinn-labs-data" / "inputs").resolve()


def test_bootstrap_creates_empty_templates_dir_without_copying_repo(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    from core.data_layout import bootstrap_if_needed, get_writable_root

    bootstrap_if_needed()
    writable_tpl = get_writable_root() / "templates"
    assert writable_tpl.is_dir()
    assert list(writable_tpl.glob("*.json")) == []


def test_bootstrap_seeds_settings_and_upload_works_under_vercel(
    monkeypatch, tmp_path
) -> None:
    """Regression: Vercel FS is read-only except /tmp; uploads must not 500."""

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import ui.app as ui_app
    from main import app

    client = app.test_client()
    settings = {
        "inputs": {
            "directory": "inputs",
            "category_key": "p",
            "files": {"p": {"event_source": "game.xlsx"}},
        },
    }
    monkeypatch.setattr(ui_app, "load_settings", lambda: settings)
    monkeypatch.setattr(
        ui_app,
        "infer_date_range_from_excel_paths",
        lambda _paths: (None, None),
    )

    bio = io.BytesIO()
    pd.DataFrame([{"Date": "2026-05-01"}]).to_excel(bio, index=False)
    bio.seek(0)

    rv = client.post(
        "/upload",
        data={"category_key": "p", "event_source": (bio, "ignored.xlsx")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200, rv.get_data(as_text=True)
    assert rv.is_json
    from core.data_layout import get_writable_root

    dest = get_writable_root() / "inputs" / "game.xlsx"
    assert dest.is_file()


def test_bootstrap_syncs_config_from_blob(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")

    store: dict[str, bytes] = {}

    class FakeClient:
        def head(self, blob_key: str) -> None:
            if blob_key not in store:
                raise FileNotFoundError(blob_key)

        def upload_file(self, local_path, path, **kwargs):
            store[path] = Path(local_path).read_bytes()

        def download_file(self, url_or_path, local_path, **kwargs):
            dest = Path(local_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(store[url_or_path])

        def list_objects(self, *, prefix=None, cursor=None, limit=None, mode=None):
            from tests.test_blob_store import _FakeBlobItem, _FakeListResult

            blobs = [
                _FakeBlobItem(k)
                for k in sorted(store)
                if prefix is None or k.startswith(prefix)
            ]
            return _FakeListResult(blobs)

        def delete(self, url_or_path) -> None:
            store.pop(url_or_path, None)

    import core.blob_store as blob_store

    monkeypatch.setattr(blob_store, "_client", FakeClient())

    from core.data_layout import REPO_ROOT, bootstrap_if_needed, get_writable_root

    repo_settings = REPO_ROOT / "config" / "settings.yaml"
    store["serinn-labs/config/settings.yaml"] = repo_settings.read_bytes()

    bootstrap_if_needed()
    local_settings = get_writable_root() / "config" / "settings.yaml"
    assert local_settings.is_file()
    assert "ATP" in local_settings.read_text(encoding="utf-8")
