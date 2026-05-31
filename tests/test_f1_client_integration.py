"""Full-client F1 integration test — schedule, standings, and template pack."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from core.template_upload import parse_uploaded_template_file

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "f1_client"
SAMPLE_CSV = (
    Path(__file__).resolve().parent.parent / "samples" / "f1_client_generation_sample.csv"
)
REPO_ROOT = Path(__file__).resolve().parent.parent
F1_SCHEDULE_PROFILE = REPO_ROOT / "config/input_profiles/f1__event-source__f1_schedule.yaml"
F1_STANDINGS_PROFILE = REPO_ROOT / "config/input_profiles/f1__metric-source__f1-standings.yaml"


def _write_templates_from_xlsx(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    raw_bytes = (FIXTURE_DIR / "CLAUDE_F1_2026_Question_Templates.xlsx").read_bytes()
    for row in parse_uploaded_template_file(
        "CLAUDE_F1_2026_Question_Templates.xlsx", raw_bytes
    ):
        template_id = str(row.get("id") or "").strip()
        if not template_id:
            continue
        (template_dir / f"{template_id}.json").write_text(
            json.dumps(row, indent=2) + "\n",
            encoding="utf-8",
        )


def _f1_settings(*, input_dir: Path, template_dir: Path) -> dict[str, object]:
    return {
        "openai_api_key": "",
        "topic_import_id": "f1-monaco-grand-prix-2026-race",
        "subcategory": "F1",
        "templates_directory": str(template_dir),
        "date_filter": {"start": "2026-06-01", "end": "2026-06-08"},
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            },
            "f1": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            },
        },
        "event_generation": {"use_llm": False},
        "inputs": {
            "directory": str(input_dir),
            "category_key": "f1",
            "files": {
                "F1": {
                    "schedule": "F1_schedule_2026.xlsx",
                    "stats": "2026_F1_Drivers_Standings.xlsx",
                },
            },
            "file_roles": {
                "F1": {
                    "schedule": "event_source",
                    "stats": "metric_source",
                },
            },
            "packages": {
                "f1": {
                    "competition_format": "field",
                    "race_session_values": ["Race"],
                    "placeholder_home_team": "Driver_A",
                    "placeholder_away_team": "Driver_B",
                },
            },
        },
        "parsing": {"persist_profiles": False},
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding=CSV_WRITE_ENCODING) as fh:
        return list(csv.DictReader(fh))


@pytest.mark.integration
def test_f1_client_pack_generates_sample_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()
    shutil.copy(F1_SCHEDULE_PROFILE, prof_dir / "f1_schedule.yaml")
    shutil.copy(F1_STANDINGS_PROFILE, prof_dir / "f1_standings.yaml")
    monkeypatch.setattr(
        "core.parsers.profiles._PROFILE_DIR",
        prof_dir,
    )

    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()
    shutil.copy(FIXTURE_DIR / "F1_schedule_2026.xlsx", input_dir)
    shutil.copy(FIXTURE_DIR / "2026_F1_Drivers_Standings.xlsx", input_dir)
    _write_templates_from_xlsx(template_dir)

    settings = _f1_settings(input_dir=input_dir, template_dir=template_dir)
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)

    def _forbid_batch_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("BatchExecutor should not run when event_generation.use_llm is false")

    monkeypatch.setattr("core.pipeline.BatchExecutor", _forbid_batch_executor)

    result = run_pipeline(settings, category_key="f1")

    assert result.success is True, result.message
    assert result.output_csv is not None

    rows = _read_csv(result.output_csv)
    assert rows, "expected at least one output row"

    SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(result.output_csv, SAMPLE_CSV)

    questions = [row["question"] for row in rows]
    assert not any("[DRIVER]" in q or "[TEAM]" in q or "[PLAYER]" in q for q in questions)

    top10 = [q for q in questions if "finish in the top 10" in q]
    assert len(top10) >= 15, f"expected ~20 driver top-10 rows, got {len(top10)}"
    assert any("Antonelli" in q for q in top10)

    team_pts = [q for q in questions if "both cars finish in the points" in q]
    assert len(team_pts) >= 8, f"expected constructor fan-out, got {len(team_pts)}"
    assert any("Mercedes" in q for q in team_pts)

    assert any("Which driver will start from pole" in q for q in questions)
    assert len(rows) > 40, "driver and team expansion should increase row count vs pre-fix ~17"
