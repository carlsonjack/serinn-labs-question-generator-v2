from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.template_config import (
    QuestionTemplate,
    load_template_dir,
    load_template_file,
    parse_template_dict,
    resolve_templates_directory,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_TEMPLATES = ROOT / "tests" / "fixtures" / "shipped_templates"
TEMPLATES = ROOT / "templates"


def test_load_all_shipped_templates() -> None:
    templates = load_template_dir(FIXTURE_TEMPLATES)
    ids = set(templates.keys())
    assert {
        "mlb_game_winner",
        "mlb_win_margin_2",
        "mlb_total_runs_over_8_5",
        "mlb_home_run",
        "mlb_rbi",
        "mlb_steal_base",
        "markets_placeholder",
        "news_placeholder",
        "entertainment_placeholder",
        "sample_csv_event_yesno",
        "sample_csv_event_mc",
        "sample_csv_entity_hr",
        "f1_race_winner_head_to_head",
        "f1_race_winner_flag",
        "f1_race_winner_yes_no",
        "f1_race_finish_ahead_yes_no",
        "mls_sample_event_yesno",
        "mls_sample_event_mc",
        "mls_sample_entity_goals",
        "stocks_daily_close_higher",
        "stocks_daily_biggest_gainer",
        "stocks_quarterly_biggest_loser",
        "music-yn-01",
        "music-mc-01",
    } <= ids
    assert templates["mlb_game_winner"].question_family == "event"
    assert templates["mlb_game_winner"].answer_type == "multiple_choice"
    assert isinstance(templates["mlb_game_winner"].priority, int)
    assert templates["mlb_total_runs_over_8_5"].line == 8.5
    assert templates["mlb_home_run"].stat_column == "HR"
    assert templates["mlb_home_run"].top_n_per_team == 2
    assert templates["markets_placeholder"]._comment == "extend by adding question and input package definition"
    assert templates["stocks_daily_close_higher"].question_family == "stock"
    assert templates["stocks_daily_close_higher"].answer_options == ""
    assert templates["stocks_daily_close_higher"].timeframe == "Daily"
    assert templates["music-yn-01"].question_family == "content"
    assert templates["music-yn-01"].answer_options == ""


def test_parse_template_roundtrip_minimal_event() -> None:
    raw = {
        "id": "x",
        "subcategory": "MLB",
        "question_family": "event",
        "question": "Q?",
        "answer_type": "multiple_choice",
        "answer_options": "A||B",
        "priority": 1,
        "requires_entities": False,
    }
    t = parse_template_dict(raw)
    assert isinstance(t, QuestionTemplate)
    assert t.priority == 1


def test_rejects_unknown_key() -> None:
    raw = {
        "id": "x",
        "subcategory": "MLB",
        "question_family": "event",
        "question": "Q?",
        "answer_type": "multiple_choice",
        "answer_options": "A||B",
        "priority": 1,
        "requires_entities": False,
        "extra": 1,
    }
    with pytest.raises(ValueError, match="Unknown keys"):
        parse_template_dict(raw)


def test_load_template_file_invalid_fixture(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "only_id"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_template_file(bad)


def test_resolve_templates_directory_from_settings() -> None:
    assert resolve_templates_directory({"templates_directory": "templates"}) == TEMPLATES


def test_duplicate_template_ids_raise(tmp_path: Path) -> None:
    body = {
        "id": "dup",
        "subcategory": "MLB",
        "question_family": "event",
        "question": "Q?",
        "answer_type": "yes_no",
        "answer_options": "Yes||No",
        "priority": "",
        "requires_entities": False,
    }
    (tmp_path / "a.json").write_text(json.dumps(body), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate template id"):
        load_template_dir(tmp_path)
