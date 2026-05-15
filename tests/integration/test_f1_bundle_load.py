"""Integration: F1 workbook → ``load_normalized_bundle`` (committed profile + isolated dirs)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.parsers.contracts import ValidationSeverity
from core.parsers import profiles as profiles_module
from core.parsers.service import load_normalized_bundle
from tests.fixtures.workbooks import write_f1_schedule_minimal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
F1_PROFILE_SRC = REPO_ROOT / "config/input_profiles/f1__event-source__f1_schedule.yaml"


@pytest.mark.integration
def test_f1_bundle_loads_race_events_with_isolated_profile_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()
    shutil.copy(F1_PROFILE_SRC, prof_dir / "f1_profile.yaml")
    monkeypatch.setattr(profiles_module, "_PROFILE_DIR", prof_dir)

    inp = tmp_path / "inputs"
    inp.mkdir()
    write_f1_schedule_minimal(inp / "f1_schedule.xlsx")

    settings: dict = {
        "inputs": {
            "directory": str(inp),
            "category_key": "F1",
            "files": {"F1": {"schedule": "f1_schedule.xlsx"}},
            "file_roles": {"F1": {"schedule": "event_source"}},
            "packages": {
                "f1": {
                    "race_session_values": ["Race"],
                    "placeholder_home_team": "Driver_A",
                    "placeholder_away_team": "Driver_B",
                },
            },
        },
        "date_filter": {"start": "2026-01-01", "end": "2026-12-31"},
        "parsing": {"persist_profiles": False},
    }

    bundle = load_normalized_bundle(settings, category_key="F1")
    errors = [i for i in bundle.issues if i.severity == ValidationSeverity.ERROR]
    assert not errors
    assert len(bundle.events) == 1
    ev = bundle.events[0]
    assert ev.event_id == "FXTEST002"
    assert ev.subcategory == "F1"
    assert ev.event_display == "Integration GP - Race"
    assert ev.home_team == "Driver_A"
    assert ev.away_team == "Driver_B"
