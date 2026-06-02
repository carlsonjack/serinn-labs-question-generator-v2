"""Full-client golf H2H integration test — schedule matchups and template."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from core.template_upload import parse_uploaded_template_file

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golf_h2h_client"
SAMPLE_CSV = (
    Path(__file__).resolve().parent.parent / "samples" / "golf_h2h_client_generation_sample.csv"
)
PROFILE_DIR = FIXTURE_DIR / "profiles"


def _write_templates_from_xlsx(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    raw_bytes = (FIXTURE_DIR / "CLAUDE_H2H_Template_Fixed.xlsx").read_bytes()
    for row in parse_uploaded_template_file("CLAUDE_H2H_Template_Fixed.xlsx", raw_bytes):
        template_id = str(row.get("id") or "").strip()
        if not template_id:
            continue
        (template_dir / f"{template_id}.json").write_text(
            json.dumps(row, indent=2) + "\n",
            encoding="utf-8",
        )


def _golf_h2h_settings(*, input_dir: Path, template_dir: Path) -> dict[str, object]:
    return {
        "openai_api_key": "",
        "topic_import_id": "pga-the-memorial-tournament-presented-by-workday-2026",
        "subcategory": "GOLF",
        "templates_directory": str(template_dir),
        "date_filter": {"start": "2026-06-01", "end": "2026-06-08"},
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            },
            "golf": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            },
        },
        "event_generation": {"use_llm": False},
        "inputs": {
            "directory": str(input_dir),
            "category_key": "golf",
            "files": {
                "golf": {
                    "event_source": "CLAUDE_Schedule_Fixed.xlsx",
                    "metric_source": "Memorial_Tournament_Field.xlsx",
                },
            },
            "file_roles": {
                "golf": {
                    "event_source": "event_source",
                    "metric_source": "metric_source",
                },
            },
            "packages": {
                "golf": {
                    "competition_format": "field",
                    "placeholder_home_team": "Golfer_A",
                    "placeholder_away_team": "Golfer_B",
                    "field_team_code": "FIELD",
                    "ascending_stat_columns": ["RANK", "FedExCup Rank"],
                    "skip_status_values": ["complete", "cancelled", "canceled"],
                },
            },
        },
        "parsing": {"persist_profiles": False},
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding=CSV_WRITE_ENCODING) as fh:
        return list(csv.DictReader(fh))


@pytest.mark.integration
def test_golf_h2h_client_pack_generates_sample_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()
    shutil.copy(PROFILE_DIR / "golf_h2h_schedule.yaml", prof_dir / "golf_h2h_schedule.yaml")
    shutil.copy(PROFILE_DIR / "golf_h2h_stats.yaml", prof_dir / "golf_h2h_stats.yaml")
    monkeypatch.setattr(
        "core.parsers.profiles._PROFILE_DIR",
        prof_dir,
    )

    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()
    shutil.copy(FIXTURE_DIR / "CLAUDE_Schedule_Fixed.xlsx", input_dir)
    shutil.copy(FIXTURE_DIR / "Memorial_Tournament_Field.xlsx", input_dir)
    _write_templates_from_xlsx(template_dir)

    settings = _golf_h2h_settings(input_dir=input_dir, template_dir=template_dir)
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)

    def _forbid_batch_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("BatchExecutor should not run when event_generation.use_llm is false")

    monkeypatch.setattr("core.pipeline.BatchExecutor", _forbid_batch_executor)

    result = run_pipeline(settings, category_key="golf")

    assert result.success is True, result.message
    assert result.output_csv is not None

    rows = _read_csv(result.output_csv)
    assert rows, "expected at least one output row"

    SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(result.output_csv, SAMPLE_CSV)

    assert len(rows) == 10, f"expected one row per schedule matchup, got {len(rows)}"

    questions = [row["question"] for row in rows]
    assert not any(
        token in q
        for q in questions
        for token in ("Golfer_A", "Golfer_B", "[GOLFER]", "[PLAYER]")
    )
    assert any("S. Scheffler" in q and "Cam. Young" in q for q in questions)

    for row in rows:
        assert row["event"] == "the Memorial Tournament presented by Workday 2026"
        opts = row["answer_options"].split("||")
        assert len(opts) == 2
        assert opts[0] in row["question"]
        assert opts[1] in row["question"]
        assert "Golfer_A" not in row["answer_options"]

    assert len({row["question"] for row in rows}) == 10
