"""Tests for multi-vertical input resolution (load_normalized_bundle prerequisites)."""

from __future__ import annotations

from pathlib import Path

from core.parsers.contracts import SourceRole
from core.parsers.service import resolve_input_scan_jobs


def test_legacy_mlb_slots_resolve_two_paths(tmp_path: Path) -> None:
    (tmp_path / "schedule.xlsx").touch()
    (tmp_path / "stats.xlsx").touch()
    settings = {
        "inputs": {
            "files": {
                "mlb": {
                    "event_source": "schedule.xlsx",
                    "metric_source": "stats.xlsx",
                },
            },
        },
    }
    fc = settings["inputs"]["files"]["mlb"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="mlb",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="mlb",
    )
    assert not issues
    assert len(jobs) == 2
    assert jobs[0][1] == SourceRole.EVENT_SOURCE
    assert jobs[1][1] == SourceRole.METRIC_SOURCE


def test_dynamic_package_requires_file_roles(tmp_path: Path) -> None:
    (tmp_path / "a.xlsx").touch()
    settings = {
        "inputs": {
            "files": {"f1": {"custom_feed": "a.xlsx"}},
        },
    }
    fc = settings["inputs"]["files"]["f1"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="f1",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="f1",
    )
    assert not jobs
    assert issues and issues[0].code == "missing_file_roles"


def test_infer_roles_schedule_slot_without_file_roles(tmp_path: Path) -> None:
    (tmp_path / "f1_schedule.xlsx").touch()
    settings = {
        "inputs": {
            "files": {"f1": {"schedule": "f1_schedule.xlsx"}},
        },
    }
    fc = settings["inputs"]["files"]["f1"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="f1",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="f1",
    )
    assert not issues
    assert len(jobs) == 1
    assert jobs[0][1] == SourceRole.EVENT_SOURCE


def test_infer_roles_arbitrary_filenames_schedule_and_stats_slots(tmp_path: Path) -> None:
    (tmp_path / "any_schedule_name.xlsx").touch()
    (tmp_path / "totally_custom_stats.xlsx").touch()
    settings = {
        "inputs": {
            "files": {
                "soccer": {
                    "schedule": "any_schedule_name.xlsx",
                    "stats": "totally_custom_stats.xlsx",
                },
            },
        },
    }
    fc = settings["inputs"]["files"]["soccer"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="soccer",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="soccer",
    )
    assert not issues
    assert len(jobs) == 2
    roles = {j[1] for j in jobs}
    assert roles == {SourceRole.EVENT_SOURCE, SourceRole.METRIC_SOURCE}


def test_explicit_file_roles_override_infer_per_slot(tmp_path: Path) -> None:
    (tmp_path / "x.xlsx").touch()
    settings = {
        "inputs": {
            "files": {"F1": {"schedule": "x.xlsx"}},
            "file_roles": {"F1": {"schedule": "metric_source"}},
        },
    }
    fc = settings["inputs"]["files"]["F1"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="F1",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="F1",
    )
    assert not issues
    assert len(jobs) == 1
    assert jobs[0][1] == SourceRole.METRIC_SOURCE


def test_partial_explicit_file_roles_other_slots_inferred(tmp_path: Path) -> None:
    (tmp_path / "a.xlsx").touch()
    (tmp_path / "b.xlsx").touch()
    settings = {
        "inputs": {
            "files": {"F1": {"schedule": "a.xlsx", "stats": "b.xlsx"}},
            "file_roles": {"F1": {"schedule": "event_source"}},
        },
    }
    fc = settings["inputs"]["files"]["F1"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="F1",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="F1",
    )
    assert not issues
    assert len(jobs) == 2
    assert {j[1] for j in jobs} == {SourceRole.EVENT_SOURCE, SourceRole.METRIC_SOURCE}


def test_dynamic_f1_single_slot(tmp_path: Path) -> None:
    (tmp_path / "f1_schedule.xlsx").touch()
    settings = {
        "inputs": {
            "files": {"F1": {"schedule": "f1_schedule.xlsx"}},
            "file_roles": {"F1": {"schedule": "event_source"}},
        },
    }
    fc = settings["inputs"]["files"]["F1"]
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key="F1",
        input_dir=tmp_path,
        file_config=fc,
        matched_pkg_key="F1",
    )
    assert not issues
    assert len(jobs) == 1
    assert jobs[0][1] == SourceRole.EVENT_SOURCE
