"""Season-scoped sports template helpers."""

from __future__ import annotations

import pytest

from core.generation.event_fill import resolve_event_answer_options
from core.generation.season_scope import (
    build_season_event,
    is_season_scope,
    unique_schedule_teams,
    uses_schedule_teams,
)
from core.parsers.contracts import NormalizedEvent
from core.pipeline import resolve_top_n_per_team
from core.template_config.schema import QuestionTemplate, parse_template_dict


def _event(home: str, away: str, eid: str = "E1") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=eid,
        subcategory="WNBA",
        home_team=home,
        away_team=away,
        event_datetime="2026-05-08T19:00:00",
    )


def _championship_template(**kwargs: object) -> QuestionTemplate:
    defaults = {
        "id": "WNBA-007",
        "subcategory": "WNBA",
        "question_family": "event",
        "question": "Who will win the WNBA Championship?",
        "answer_type": "multiple_choice",
        "answer_options": "{schedule_teams}",
        "priority": 1,
        "requires_entities": False,
        "generation_scope": "season",
    }
    defaults.update(kwargs)
    return QuestionTemplate(**defaults)  # type: ignore[arg-type]


class TestSeasonScopeHelpers:
    def test_is_season_scope(self):
        assert is_season_scope(_championship_template()) is True
        assert is_season_scope(_championship_template(generation_scope=None)) is False
        assert is_season_scope(_championship_template(generation_scope="event")) is False

    def test_uses_schedule_teams(self):
        assert uses_schedule_teams(_championship_template()) is True
        assert uses_schedule_teams(_championship_template(answer_options="{team_options}")) is True
        assert uses_schedule_teams(_championship_template(answer_options="{entity_options}")) is False

    def test_unique_schedule_teams_dedupes_and_sorts(self):
        events = [
            _event("Seattle Storm", "Las Vegas Aces", "E1"),
            _event("Indiana Fever", "Seattle Storm", "E2"),
            _event("Chicago Sky", "Indiana Fever", "E3"),
        ]
        teams = unique_schedule_teams(events)
        assert teams == [
            "Chicago Sky",
            "Indiana Fever",
            "Las Vegas Aces",
            "Seattle Storm",
        ]

    def test_build_season_event_label(self):
        events = [_event("A", "B")]
        ev = build_season_event("WNBA", events, {"end": "2026-09-27"})
        assert ev.event_display == "WNBA 2026 Season"
        assert ev.home_team == ""
        assert ev.away_team == ""
        assert ev.event_datetime == "2026-05-08T19:00:00"

    def test_resolve_schedule_teams_answer_options(self):
        tpl = _championship_template()
        teams = ["Atlanta Dream", "Chicago Sky"]
        opts = resolve_event_answer_options(
            tpl,
            build_season_event("WNBA", [_event("A", "B")]),
            [],
            schedule_teams=teams,
        )
        assert opts == "Atlanta Dream||Chicago Sky"

    def test_resolve_top_n_defaults_to_20_for_season_entity_stat(self):
        tpl = QuestionTemplate(
            id="WNBA-008",
            subcategory="WNBA",
            question_family="entity_stat",
            question="Who will lead the league in points?",
            answer_type="multiple_choice",
            answer_options="{entity_options}",
            priority=1,
            requires_entities=True,
            stat_column="PTS",
            generation_scope="season",
        )
        assert resolve_top_n_per_team(tpl, {}) == 20
        assert resolve_top_n_per_team(tpl, {"top_n_per_team": 5}) == 5

    def test_resolve_top_n_template_value_beats_global_override(self):
        tpl = QuestionTemplate(
            id="GOLF01",
            subcategory="GOLF",
            question_family="entity_stat",
            question="Who will win the {event_name}?",
            answer_type="multiple_choice",
            answer_options="{entity_options}",
            priority=1,
            requires_entities=True,
            stat_column="FedExCup Rank",
            top_n_per_team=35,
        )
        assert resolve_top_n_per_team(tpl, {"top_n_per_team": 3}) == 35


class TestSeasonSchemaValidation:
    def test_parses_season_championship_template(self):
        raw = {
            "id": "WNBA-007",
            "subcategory": "WNBA",
            "question_family": "event",
            "question": "Who will win the WNBA Championship?",
            "answer_type": "multiple_choice",
            "answer_options": "{schedule_teams}",
            "priority": 1,
            "requires_entities": False,
            "generation_scope": "season",
        }
        tpl = parse_template_dict(raw)
        assert tpl.generation_scope == "season"

    def test_rejects_schedule_teams_on_entity_stat(self):
        raw = {
            "id": "bad",
            "subcategory": "WNBA",
            "question_family": "entity_stat",
            "question": "Who wins?",
            "answer_type": "multiple_choice",
            "answer_options": "{schedule_teams}",
            "priority": 1,
            "requires_entities": True,
            "stat_column": "PTS",
            "top_n_per_team": 2,
            "generation_scope": "season",
        }
        with pytest.raises(ValueError, match="question_family=event"):
            parse_template_dict(raw)

    def test_rejects_season_on_content(self):
        raw = {
            "id": "bad",
            "subcategory": "Music",
            "question_family": "content",
            "question": "Q?",
            "answer_type": "yes_no",
            "answer_options": "Yes||No",
            "priority": 1,
            "requires_entities": False,
            "generation_scope": "season",
        }
        with pytest.raises(ValueError, match="sports event or entity_stat"):
            parse_template_dict(raw)
