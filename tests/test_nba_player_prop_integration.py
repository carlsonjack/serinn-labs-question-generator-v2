"""Full-client NBA Finals integration test for [PLAYER] row expansion.

Uses the client's 57-template pack plus Finals schedule/stats fixtures.
Regenerates ``samples/nba_player_prop_generation_sample.csv`` on each pass so
operators can visually validate output.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from core.template_upload import parse_uploaded_template_file

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "nba_player_prop"
SAMPLE_CSV = (
    Path(__file__).resolve().parent.parent / "samples" / "nba_player_prop_generation_sample.csv"
)


def _write_templates_from_xlsx(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    raw_bytes = (FIXTURE_DIR / "57_Templates.xlsx").read_bytes()
    for row in parse_uploaded_template_file("57_Templates.xlsx", raw_bytes):
        template_id = str(row.get("id") or "").strip()
        if not template_id:
            continue
        (template_dir / f"{template_id}.json").write_text(
            json.dumps(row, indent=2) + "\n",
            encoding="utf-8",
        )


def _nba_settings(*, input_dir: Path, template_dir: Path) -> dict[str, object]:
    return {
        "openai_api_key": "",
        "topic_import_id": "nba-finals-2026",
        "subcategory": "NBA",
        "top_n_per_team": 2,
        "templates_directory": str(template_dir),
        "date_filter": {"start": "2026-05-29", "end": "2026-06-20"},
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            }
        },
        "event_generation": {"use_llm": False},
        "inputs": {
            "directory": str(input_dir),
            "category_key": "nba",
            "files": {
                "nba": {
                    "event_source": "NBA_Finals_2026_schedule.xlsx",
                    "metric_source": "COMBINED_NYK_vs_OKC_Stats.xlsx",
                }
            },
            "package_aliases": {"nba": ["NBA"]},
        },
        "parsing": {"persist_profiles": False},
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding=CSV_WRITE_ENCODING) as fh:
        return list(csv.DictReader(fh))


@pytest.mark.integration
def test_nba_player_prop_full_client_pack_generates_sample_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end deterministic run on client Finals fixtures.

    Game 1–4 wording is bound to every schedule row by template authoring — not
    filtered by round in this feature.
    """

    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()
    shutil.copy(FIXTURE_DIR / "NBA_Finals_2026_schedule.xlsx", input_dir)
    shutil.copy(FIXTURE_DIR / "COMBINED_NYK_vs_OKC_Stats.xlsx", input_dir)
    _write_templates_from_xlsx(template_dir)

    settings = _nba_settings(input_dir=input_dir, template_dir=template_dir)
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)

    def _forbid_batch_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("BatchExecutor should not run when event_generation.use_llm is false")

    monkeypatch.setattr("core.pipeline.BatchExecutor", _forbid_batch_executor)

    result = run_pipeline(settings, category_key="nba")

    assert result.success is True, result.message
    assert result.output_csv is not None

    rows = _read_csv(result.output_csv)
    assert rows, "expected at least one output row"

    SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(result.output_csv, SAMPLE_CSV)

    assert not any("[PLAYER]" in row["question"] for row in rows)

    brunson_rows = [row for row in rows if "Jalen Brunson" in row["question"]]
    assert brunson_rows, "expected at least one Jalen Brunson player-prop row"
    assert "Under 18" in brunson_rows[0]["answer_options"]

    mc_prop_rows = [
        row
        for row in rows
        if any(marker in row["answer_options"] for marker in ("Under 18", "0-3||4-6", "0-2||3-4"))
    ]
    assert mc_prop_rows, "expected bucket-style answer_options on MC player-prop rows"

    for player_name in ("Jalen Brunson", "Karl-Anthony Towns", "Shai Gilgeous-Alexander"):
        assert not any(
            row["answer_options"] == player_name
            or row["answer_options"].startswith(f"{player_name}||")
            for row in mc_prop_rows
        ), f"player name should not appear as MC answer_options: {player_name}"

    yn_prop_rows = [
        row
        for row in rows
        if "double-double" in row["question"].lower() or "triple-double" in row["question"].lower()
    ]
    assert yn_prop_rows
    assert all(row["answer_options"] == "Yes||No" for row in yn_prop_rows)
    assert not any("[PLAYER]" in row["question"] for row in yn_prop_rows)

    winner_rows = [row for row in rows if row["question"].startswith("Who will win Game")]
    assert winner_rows
    assert all("||" in row["answer_options"] for row in winner_rows)

    assert len(rows) > 400, "player-prop expansion should materially increase row count vs pre-fix run"
