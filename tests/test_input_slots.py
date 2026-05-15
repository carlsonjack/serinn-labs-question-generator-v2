"""Input slot resolution from settings."""

from __future__ import annotations

import pytest

from core.input_slots import (
    get_files_map_for_category,
    get_inputs_category_key,
    iter_input_slots,
    list_input_categories,
    normalize_inputs_files,
    resolve_inputs_package_file_key,
)


def test_get_inputs_category_key_explicit():
    s = {"inputs": {"category_key": "markets", "files": {"mlb": {}, "markets": {}}}}
    assert get_inputs_category_key(s) == "markets"


def test_get_inputs_category_key_falls_back_to_first_file_group():
    s = {"inputs": {"files": {"zebra": {"a": "1.xlsx"}, "mlb": {"b": "2.xlsx"}}}}
    assert get_inputs_category_key(s) == "mlb"


def test_iter_input_slots_order_and_labels():
    s = {
        "inputs": {
            "category_key": "mlb",
            "files": {
                "mlb": {
                    "metric_source": "stats.xlsx",
                    "event_source": "schedule.xlsx",
                }
            },
        }
    }
    slots = iter_input_slots(s)
    assert [x["slot_id"] for x in slots] == ["event_source", "metric_source"]
    assert slots[0]["target_filename"] == "schedule.xlsx"
    assert slots[0]["label"] == "Event source"


def test_get_files_map():
    s = {
        "inputs": {
            "files": {
                "x": {"one": "a.xlsx", "two": "b.xlsx"},
            }
        }
    }
    assert get_files_map_for_category(s, "x") == {"one": "a.xlsx", "two": "b.xlsx"}


def test_list_input_categories():
    s = {"inputs": {"files": {"mlb": {}, "markets": {}}}}
    assert list_input_categories(s) == ["markets", "mlb"]


def test_resolve_inputs_package_file_key_exact_and_case_insensitive():
    s = {
        "inputs": {
            "files": {
                "MLS": {"event_source": "schedule.xlsx"},
                "mlb": {"event_source": "a.xlsx"},
            }
        }
    }
    assert resolve_inputs_package_file_key(s, "MLS") == "MLS"
    assert resolve_inputs_package_file_key(s, "mls") == "MLS"
    assert resolve_inputs_package_file_key(s, "mlb") == "mlb"
    assert resolve_inputs_package_file_key(s, "nope") is None


def test_normalize_inputs_files_ok():
    raw = {
        "mlb": {"event_source": "schedule.xlsx", "metric_source": "stats.xlsx"},
        "markets": {"quotes": "quotes.xlsx"},
    }
    assert normalize_inputs_files(raw) == raw


def test_normalize_inputs_files_rejects_bad_key():
    with pytest.raises(ValueError, match="Invalid input package"):
        normalize_inputs_files({"bad-key": {"a": "x.xlsx"}})


def test_normalize_inputs_files_rejects_path_in_filename():
    with pytest.raises(ValueError, match="Invalid filename"):
        normalize_inputs_files({"mlb": {"a": "../x.xlsx"}})


def test_save_settings_yaml_replaces_inputs_files_entirely(tmp_path, monkeypatch):
    from core.config import load_settings_disk_only, save_settings_yaml

    cfg = tmp_path / "settings.yaml"
    monkeypatch.setattr("core.config._SETTINGS", cfg)
    monkeypatch.setattr("core.config._SETTINGS_LOCAL", tmp_path / "missing.local.yaml")

    cfg.write_text(
        "inputs:\n"
        "  directory: inputs\n"
        "  category_key: mlb\n"
        "  files:\n"
        "    mlb:\n"
        "      event_source: a.xlsx\n"
        "    old:\n"
        "      x: y.xlsx\n",
        encoding="utf-8",
    )
    save_settings_yaml(
        {"_inputs_files": {"mlb": {"event_source": "schedule.xlsx"}}}
    )
    data = load_settings_disk_only()
    assert "old" not in (data.get("inputs") or {}).get("files", {})
    assert data["inputs"]["files"]["mlb"]["event_source"] == "schedule.xlsx"
