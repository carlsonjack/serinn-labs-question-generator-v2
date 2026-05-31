"""Full-client golf integration test — schedule, rankings, and template pack."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from core.template_upload import parse_uploaded_template_file

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golf_client"
SAMPLE_CSV = (
    Path(__file__).resolve().parent.parent / "samples" / "golf_client_generation_sample.csv"
)
PROFILE_DIR = FIXTURE_DIR / "profiles"


def _write_templates_from_xlsx(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    raw_bytes = (FIXTURE_DIR / "SHWAB_TEST.xlsx").read_bytes()
    for row in parse_uploaded_template_file("SHWAB_TEST.xlsx", raw_bytes):
        template_id = str(row.get("id") or "").strip()
        if not template_id:
            continue
        (template_dir / f"{template_id}.json").write_text(
            json.dumps(row, indent=2) + "\n",
            encoding="utf-8",
        )


def _golf_settings(*, input_dir: Path, template_dir: Path) -> dict[str, object]:
    return {
        "openai_api_key": "",
        "topic_import_id": "pga-charles-schwab-challenge-2026",
        "subcategory": "GOLF",
        "templates_directory": str(template_dir),
        "date_filter": {"start": "2026-05-28", "end": "2026-06-03"},
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
                    "event_source": "2026_Schedule.xlsx",
                    "metric_source": "Charles_Schwab_stats.xlsx",
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
def test_golf_client_pack_generates_sample_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()
    shutil.copy(PROFILE_DIR / "golf_schedule.yaml", prof_dir / "golf_schedule.yaml")
    shutil.copy(PROFILE_DIR / "golf_stats.yaml", prof_dir / "golf_stats.yaml")
    monkeypatch.setattr(
        "core.parsers.profiles._PROFILE_DIR",
        prof_dir,
    )

    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()
    shutil.copy(FIXTURE_DIR / "2026_Schedule.xlsx", input_dir)
    shutil.copy(FIXTURE_DIR / "Charles_Schwab_stats.xlsx", input_dir)
    _write_templates_from_xlsx(template_dir)

    settings = _golf_settings(input_dir=input_dir, template_dir=template_dir)
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

    questions = [row["question"] for row in rows]
    assert not any(
        token in q for q in questions for token in ("[GOLFER]", "[PLAYER]", "[DRIVER]")
    )

    winner_rows = [row for row in rows if row["question"].startswith("Who will win the Charles Schwab")]
    assert winner_rows, "expected per-tournament winner question"
    assert winner_rows[0]["event"] == "Charles Schwab Challenge 2026"
    assert "GOLF 2026 Season" not in winner_rows[0]["question"]

    birdie_props = [q for q in questions if "record more than 3 birdies" in q]
    assert len(birdie_props) >= 5, f"expected golfer prop fan-out, got {len(birdie_props)}"
    assert any("Ludvig Aberg" in q or "Scottie Scheffler" in q for q in birdie_props)

    fedex_row = next(row for row in rows if row["question"] == "Who will win the FedEx Cup?")
    assert fedex_row["event"] == "GOLF 2026 Season"
    assert "Ludvig Aberg" in fedex_row["answer_options"]
    assert "Adrien Saddier" not in fedex_row["answer_options"]

    assert len(rows) > 80, "golfer prop expansion should materially increase row count vs pre-fix ~33"
