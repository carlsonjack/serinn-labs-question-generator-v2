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
