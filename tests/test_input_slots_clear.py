"""Input slot file clearing when switching packages or partial uploads."""

from __future__ import annotations

from core.input_slots import (
    clear_category_input_files,
    clear_unuploaded_category_input_files,
)


def test_clear_category_input_files_removes_configured_targets(tmp_path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    (input_dir / "schedule.xlsx").write_bytes(b"a")
    (input_dir / "stats.xlsx").write_bytes(b"b")
    settings = {
        "inputs": {
            "files": {
                "mlb": {
                    "event_source": "schedule.xlsx",
                    "metric_source": "stats.xlsx",
                }
            }
        }
    }

    removed = clear_category_input_files(input_dir, settings, "mlb")

    assert sorted(removed) == ["schedule.xlsx", "stats.xlsx"]
    assert not (input_dir / "schedule.xlsx").exists()
    assert not (input_dir / "stats.xlsx").exists()


def test_clear_unuploaded_category_input_files_keeps_uploaded_slots(tmp_path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    (input_dir / "schedule.xlsx").write_bytes(b"new")
    (input_dir / "stats.xlsx").write_bytes(b"stale")
    files_map = {
        "event_source": "schedule.xlsx",
        "metric_source": "stats.xlsx",
    }

    removed = clear_unuploaded_category_input_files(
        input_dir, files_map, {"event_source"}
    )

    assert removed == ["stats.xlsx"]
    assert (input_dir / "schedule.xlsx").is_file()
    assert not (input_dir / "stats.xlsx").exists()

