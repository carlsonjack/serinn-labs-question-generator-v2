"""Tests for topic import ID catalog helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import topic_import_catalog as tic


def test_load_topic_import_ids_catalog_normalizes_entries(tmp_path: Path) -> None:
    catalog = tmp_path / "topic_import_ids_catalog.json"
    catalog.write_text(
        json.dumps(
            [
                "mlb-mlb-season-2026",
                {"id": " nba-nba-season-2025-2026 ", "label": " NBA Season "},
                {"id": "", "label": "ignored"},
                {"label": "missing id"},
            ]
        ),
        encoding="utf-8",
    )

    assert tic.load_topic_import_ids_catalog(catalog) == [
        {"id": "mlb-mlb-season-2026", "label": ""},
        {"id": "nba-nba-season-2025-2026", "label": "NBA Season"},
    ]


def test_load_topic_import_ids_catalog_missing_file_returns_empty(tmp_path: Path) -> None:
    assert tic.load_topic_import_ids_catalog(tmp_path / "missing.json") == []


def test_append_creates_file_and_sorts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tic, "_CATALOG_PATH_OVERRIDE", tmp_path / "cat.json")
    r1 = tic.append_topic_import_id_to_catalog("zebra-id")
    assert r1["added"] is True
    r2 = tic.append_topic_import_id_to_catalog("alpha-id")
    assert r2["added"] is True
    r3 = tic.append_topic_import_id_to_catalog("ALPHA-ID")
    assert r3["already_exists"] is True
    data = json.loads((tmp_path / "cat.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in data] == ["alpha-id", "zebra-id"]


def test_append_rejects_invalid_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tic, "_CATALOG_PATH_OVERRIDE", tmp_path / "cat.json")
    with pytest.raises(ValueError, match="empty"):
        tic.append_topic_import_id_to_catalog("   ")
    with pytest.raises(ValueError, match="letters"):
        tic.append_topic_import_id_to_catalog("bad id")
