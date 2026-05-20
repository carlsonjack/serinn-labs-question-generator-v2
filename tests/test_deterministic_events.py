"""Deterministic sports event question assembly (no OpenAI)."""

from __future__ import annotations

import pytest

from core.generation.deterministic_events import build_deterministic_questions
from core.generation.event_fill import (
    fill_sports_template_text,
    normalize_yes_no_options,
    resolve_event_answer_options,
)
from core.generation.prompt_builder import PromptItem, fill_template_placeholders
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate


def _event(**kwargs: object) -> NormalizedEvent:
    defaults = {
        "event_id": "E1",
        "subcategory": "WNBA",
        "home_team": "Seattle Storm",
        "away_team": "Golden State Valkyries",
        "event_datetime": "2026-05-08T19:00:00",
    }
    defaults.update(kwargs)
    return NormalizedEvent(**defaults)  # type: ignore[arg-type]


def _bracket_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="WNBA-001",
        subcategory="WNBA",
        question_family="event",
        question="Who will win [HOME_TEAM] vs [AWAY_TEAM]?",
        answer_type="multiple_choice",
        answer_options="[HOME_TEAM] || [AWAY_TEAM]",
        priority=1,
        requires_entities=False,
    )


def _brace_entity_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="WNBA-002",
        subcategory="WNBA",
        question_family="entity_stat",
        question="Top scorer in {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority=1,
        requires_entities=True,
        stat_column="PTS",
        top_n_per_team=2,
    )


class TestFillSportsTemplateText:
    def test_bracket_home_away(self):
        tpl = _bracket_template()
        out = fill_sports_template_text(tpl.question, _event(), tpl)
        assert out == "Who will win Seattle Storm vs Golden State Valkyries?"

    def test_bracket_answer_options_normalized_spacing(self):
        tpl = _bracket_template()
        out = fill_sports_template_text(tpl.answer_options, _event(), tpl)
        assert "Seattle Storm" in out and "Golden State Valkyries" in out

    def test_point_total_from_line(self):
        tpl = QuestionTemplate(
            id="t",
            subcategory="WNBA",
            question_family="event",
            question="Over [POINT_TOTAL]?",
            answer_type="yes_no",
            answer_options="Yes||No",
            priority=1,
            requires_entities=False,
            line=165.5,
        )
        out = fill_sports_template_text(tpl.question, _event(), tpl)
        assert out == "Over 165.5?"


class TestResolveEventAnswerOptions:
    def test_yes_no_normalizes_spaced_pipes(self):
        tpl = QuestionTemplate(
            id="t",
            subcategory="WNBA",
            question_family="event",
            question="Q?",
            answer_type="yes_no",
            answer_options="Yes || No",
            priority=1,
            requires_entities=False,
        )
        assert (
            resolve_event_answer_options(tpl, _event(), [])
            == normalize_yes_no_options("Yes || No")
            == "Yes||No"
        )

    def test_entity_stat_joins_players(self):
        tpl = _brace_entity_template()
        players = [
            PlayerStatRecord(
                player_name="A'ja Wilson",
                team="LV",
                source_team="LV",
                stat_values={"PTS": 20.0},
                source_sheet=None,
                row_number=1,
            ),
            PlayerStatRecord(
                player_name="Skylar Diggins-Smith",
                team="SEA",
                source_team="SEA",
                stat_values={"PTS": 18.0},
                source_sheet=None,
                row_number=2,
            ),
        ]
        opts = resolve_event_answer_options(tpl, _event(), players)
        assert opts == "A'ja Wilson||Skylar Diggins-Smith"


class TestBuildDeterministicQuestions:
    def test_one_item_per_prompt(self):
        tpl = _bracket_template()
        event = _event()
        items = [PromptItem(template=tpl, event=event, players=[])]
        qs = build_deterministic_questions(items)
        assert len(qs) == 1
        assert qs[0].template_id == "WNBA-001"
        assert qs[0].event_id == "E1"
        assert "Seattle Storm" in qs[0].question
        assert "||" in qs[0].answer_options

    def test_fill_template_placeholders_delegates(self):
        tpl = _bracket_template()
        assert fill_template_placeholders(tpl, _event()) == fill_sports_template_text(
            tpl.question, _event(), tpl
        )
