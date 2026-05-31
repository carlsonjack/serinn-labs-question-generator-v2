"""Tests for [TEAM] row-expansion on event templates."""

from __future__ import annotations

from core.generation.deterministic_events import build_deterministic_questions
from core.generation.event_fill import (
    fill_sports_template_text,
    team_instance_key,
    unique_teams_from_stats,
    uses_team_question_expansion,
)
from core.generation.prompt_builder import PromptItem
from core.parsers.contracts import NormalizedBundle, NormalizedEvent, PlayerStatRecord
from core.pipeline import build_prompt_items
from core.template_config.schema import QuestionTemplate


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="monaco",
        subcategory="F1",
        home_team="Driver_A",
        away_team="Driver_B",
        event_datetime="2026-06-08T00:00:00",
        event_display="Monaco Grand Prix - Race",
    )


def _team_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="FORM09",
        subcategory="F1",
        question_family="event",
        question="Will [TEAM] have both cars finish in the points?",
        answer_type="yes_no",
        answer_options=None,
        priority=2,
        requires_entities=False,
    )


def _record(name: str, constructor: str, pts: float) -> PlayerStatRecord:
    return PlayerStatRecord(
        player_name=name,
        team="FIELD",
        source_team=constructor,
        stat_values={"PTS": pts},
        source_sheet=None,
        row_number=1,
    )


class TestTeamExpansion:
    def test_detects_team_token(self) -> None:
        assert uses_team_question_expansion(_team_tpl()) is True

    def test_unique_teams_from_stats(self) -> None:
        stats = [
            _record("Antonelli", "Mercedes", 131.0),
            _record("Russell", "Mercedes", 88.0),
            _record("Leclerc", "Ferrari", 75.0),
        ]
        assert unique_teams_from_stats(stats) == ["Ferrari", "Mercedes"]

    def test_build_prompt_items_one_per_team(self) -> None:
        tpl = _team_tpl()
        bundle = NormalizedBundle(
            events=[_event()],
            player_stats=[
                _record("Antonelli", "Mercedes", 131.0),
                _record("Russell", "Mercedes", 88.0),
                _record("Leclerc", "Ferrari", 75.0),
            ],
        )
        items = build_prompt_items(bundle, [tpl], {})
        assert len(items) == 2
        assert {item.team_label for item in items} == {"Ferrari", "Mercedes"}
        assert items[0].instance_key == team_instance_key(items[0].team_label)

    def test_deterministic_fill_team_name(self) -> None:
        tpl = _team_tpl()
        out = fill_sports_template_text(
            tpl.question, _event(), tpl, team="Mercedes"
        )
        assert out == "Will Mercedes have both cars finish in the points?"
        assert "[TEAM]" not in out

    def test_deterministic_questions_yes_no(self) -> None:
        tpl = _team_tpl()
        item = PromptItem(
            template=tpl,
            event=_event(),
            team_label="Mercedes",
            instance_key=team_instance_key("Mercedes"),
        )
        gen = build_deterministic_questions([item])[0]
        assert "Mercedes" in gen.question
        assert gen.answer_options == "Yes||No"
