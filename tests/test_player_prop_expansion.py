"""Tests for [PLAYER] row-expansion on entity_stat templates."""

from __future__ import annotations

from core.generation.deterministic_events import build_deterministic_questions
from core.generation.event_fill import (
    fill_sports_template_text,
    player_instance_key,
    resolve_event_answer_options,
    uses_player_question_expansion,
)
from core.generation.prompt_builder import GeneratedQuestion, PromptItem
from core.generation.row_assembler import RowAssembler
from core.parsers.contracts import NormalizedBundle, NormalizedEvent, PlayerStatRecord
from core.pipeline import build_prompt_items
from core.template_config.schema import QuestionTemplate


def _event(**kwargs: object) -> NormalizedEvent:
    defaults = {
        "event_id": "G1",
        "subcategory": "NBA",
        "home_team": "New York Knicks",
        "away_team": "Oklahoma City Thunder",
        "event_datetime": "2026-06-03T20:30:00",
    }
    defaults.update(kwargs)
    return NormalizedEvent(**defaults)  # type: ignore[arg-type]


def _player(name: str, team: str, pts: float) -> PlayerStatRecord:
    return PlayerStatRecord(
        player_name=name,
        team=team,
        source_team=team,
        stat_values={"PTS": pts},
        source_sheet=None,
        row_number=1,
    )


def _player_prop_tpl(**kwargs: object) -> QuestionTemplate:
    defaults: dict[str, object] = {
        "id": "NBA-05",
        "subcategory": "NBA",
        "question_family": "entity_stat",
        "question": "How many points will [PLAYER] score in Game 1?",
        "answer_type": "multiple_choice",
        "answer_options": "Under 18||18-22||23-27||28-32||33+",
        "priority": 1,
        "requires_entities": True,
        "stat_column": "PTS",
        "top_n_per_team": 2,
    }
    defaults.update(kwargs)
    return QuestionTemplate(**defaults)  # type: ignore[arg-type]


def _classic_entity_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="NBA-CLASSIC",
        subcategory="NBA",
        question_family="entity_stat",
        question="Which player will score the most in {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority=1,
        requires_entities=True,
        stat_column="PTS",
        top_n_per_team=2,
    )


class TestUsesPlayerQuestionExpansion:
    def test_detects_bracket_player(self) -> None:
        assert uses_player_question_expansion(_player_prop_tpl()) is True

    def test_detects_brace_player(self) -> None:
        tpl = _player_prop_tpl(question="How many points will {player} score?")
        assert uses_player_question_expansion(tpl) is True

    def test_false_for_classic_entity_stat(self) -> None:
        assert uses_player_question_expansion(_classic_entity_tpl()) is False

    def test_detects_bracket_driver(self) -> None:
        tpl = _player_prop_tpl(
            id="FORM05",
            question="Will [DRIVER] finish in the top 10?",
            answer_type="yes_no",
            answer_options="Yes||No",
        )
        assert uses_player_question_expansion(tpl) is True

    def test_detects_bracket_golfer(self) -> None:
        tpl = _player_prop_tpl(
            id="GOLF02",
            subcategory="GOLF",
            question="Will [GOLFER] record more than 3 birdies in a round?",
            answer_type="yes_no",
            answer_options="Yes||No",
        )
        assert uses_player_question_expansion(tpl) is True


class TestFillSportsTemplateTextWithPlayer:
    def test_substitutes_player_name(self) -> None:
        tpl = _player_prop_tpl()
        player = _player("Jalen Brunson", "New York Knicks", 26.9)
        out = fill_sports_template_text(tpl.question, _event(), tpl, player=player)
        assert out == "How many points will Jalen Brunson score in Game 1?"
        assert "[PLAYER]" not in out

    def test_substitutes_driver_token(self) -> None:
        tpl = _player_prop_tpl(
            id="FORM05",
            question="Will [DRIVER] finish in the top 10?",
            answer_type="yes_no",
        )
        player = _player("George Russell", "Mercedes", 88.0)
        out = fill_sports_template_text(tpl.question, _event(), tpl, player=player)
        assert out == "Will George Russell finish in the top 10?"

    def test_substitutes_golfer_token(self) -> None:
        tpl = _player_prop_tpl(
            id="GOLF02",
            subcategory="GOLF",
            question="Will [GOLFER] record more than 3 birdies in a round?",
            answer_type="yes_no",
        )
        player = _player("Scottie Scheffler", "FIELD", 1.0)
        out = fill_sports_template_text(tpl.question, _event(subcategory="GOLF"), tpl, player=player)
        assert out == "Will Scottie Scheffler record more than 3 birdies in a round?"
        assert "[GOLFER]" not in out

    def test_event_driver_fallback_to_literal_word(self) -> None:
        tpl = QuestionTemplate(
            id="FORM06",
            subcategory="F1",
            question_family="event",
            question="Which [DRIVER] will start from pole position?",
            answer_type="multiple_choice",
            answer_options="A||B",
            priority=1,
            requires_entities=False,
        )
        out = fill_sports_template_text(tpl.question, _event(), tpl)
        assert out == "Which driver will start from pole position?"


class TestResolveEventAnswerOptionsPlayerProp:
    def test_preserves_stat_buckets(self) -> None:
        tpl = _player_prop_tpl()
        players = [_player("Jalen Brunson", "New York Knicks", 26.9)]
        opts = resolve_event_answer_options(tpl, _event(), players)
        assert opts == "Under 18||18-22||23-27||28-32||33+"

    def test_yes_no_player_prop(self) -> None:
        tpl = _player_prop_tpl(
            id="NBA-37",
            question="Will [PLAYER] record a double-double?",
            answer_type="yes_no",
            answer_options="Yes||No",
        )
        players = [_player("Jalen Brunson", "New York Knicks", 26.9)]
        assert resolve_event_answer_options(tpl, _event(), players) == "Yes||No"

    def test_classic_still_returns_player_names(self) -> None:
        tpl = _classic_entity_tpl()
        players = [
            _player("Jalen Brunson", "New York Knicks", 26.9),
            _player("Shai Gilgeous-Alexander", "Oklahoma City Thunder", 27.1),
        ]
        opts = resolve_event_answer_options(tpl, _event(), players)
        assert opts == "Jalen Brunson||Shai Gilgeous-Alexander"


class TestBuildPromptItemsFanOut:
    def test_one_item_per_player(self) -> None:
        tpl = _player_prop_tpl()
        bundle = NormalizedBundle(
            events=[_event()],
            player_stats=[
                _player("Jalen Brunson", "New York Knicks", 26.9),
                _player("OG Anunoby", "New York Knicks", 18.0),
                _player("Shai Gilgeous-Alexander", "Oklahoma City Thunder", 27.1),
            ],
        )
        settings: dict[str, object] = {"top_n_per_team": 2}
        items = build_prompt_items(bundle, [tpl], settings)
        assert len(items) == 3
        assert all(len(item.players) == 1 for item in items)
        assert {item.players[0].player_name for item in items} == {
            "Jalen Brunson",
            "OG Anunoby",
            "Shai Gilgeous-Alexander",
        }
        assert len({item.instance_key for item in items}) == 3

    def test_classic_single_item(self) -> None:
        tpl = _classic_entity_tpl()
        bundle = NormalizedBundle(
            events=[_event()],
            player_stats=[
                _player("Jalen Brunson", "New York Knicks", 26.9),
                _player("Shai Gilgeous-Alexander", "Oklahoma City Thunder", 27.1),
            ],
        )
        settings: dict[str, object] = {"top_n_per_team": 2}
        items = build_prompt_items(bundle, [tpl], settings)
        assert len(items) == 1
        assert len(items[0].players) == 2
        assert items[0].instance_key == ""

    def test_driver_entity_stat_fans_out(self) -> None:
        tpl = _player_prop_tpl(
            id="FORM05",
            subcategory="F1",
            question="Will [DRIVER] finish in the top 10?",
            answer_type="yes_no",
            answer_options="Yes||No",
            top_n_per_team=2,
        )
        bundle = NormalizedBundle(
            events=[_event(subcategory="F1")],
            player_stats=[
                PlayerStatRecord(
                    player_name="Antonelli",
                    team="FIELD",
                    source_team="Mercedes",
                    stat_values={"PTS": 131.0},
                    source_sheet=None,
                    row_number=1,
                ),
                PlayerStatRecord(
                    player_name="Russell",
                    team="FIELD",
                    source_team="Mercedes",
                    stat_values={"PTS": 88.0},
                    source_sheet=None,
                    row_number=2,
                ),
            ],
        )
        settings: dict[str, object] = {
            "inputs": {"category_key": "f1", "packages": {"f1": {"competition_format": "field"}}},
            "top_n_per_team": 2,
        }
        items = build_prompt_items(bundle, [tpl], settings)
        assert len(items) == 2
        assert all(item.instance_key for item in items)


class TestBuildDeterministicQuestionsPlayerProp:
    def test_distinct_questions_same_buckets(self) -> None:
        tpl = _player_prop_tpl()
        players = [
            _player("Jalen Brunson", "New York Knicks", 26.9),
            _player("Shai Gilgeous-Alexander", "Oklahoma City Thunder", 27.1),
        ]
        items = [
            PromptItem(
                template=tpl,
                event=_event(),
                players=[players[0]],
                instance_key=player_instance_key(players[0]),
            ),
            PromptItem(
                template=tpl,
                event=_event(),
                players=[players[1]],
                instance_key=player_instance_key(players[1]),
            ),
        ]
        qs = build_deterministic_questions(items)
        assert len(qs) == 2
        assert "Jalen Brunson" in qs[0].question
        assert "Shai Gilgeous-Alexander" in qs[1].question
        assert qs[0].answer_options == qs[1].answer_options == "Under 18||18-22||23-27||28-32||33+"
        assert "[PLAYER]" not in qs[0].question


class TestRowAssemblerPlayerPropKeys:
    def test_duplicate_template_event_with_instance_keys(self) -> None:
        tpl = _player_prop_tpl()
        event = _event()
        p1 = _player("Jalen Brunson", "New York Knicks", 26.9)
        p2 = _player("Shai Gilgeous-Alexander", "Oklahoma City Thunder", 27.1)
        items = [
            PromptItem(
                template=tpl,
                event=event,
                players=[p1],
                instance_key=player_instance_key(p1),
            ),
            PromptItem(
                template=tpl,
                event=event,
                players=[p2],
                instance_key=player_instance_key(p2),
            ),
        ]
        questions = [
            GeneratedQuestion(
                template_id=tpl.id,
                event_id=event.event_id,
                instance_key=player_instance_key(p2),
                question="How many points will Shai Gilgeous-Alexander score in Game 1?",
                answer_options="Under 18||18-22||23-27||28-32||33+",
            ),
            GeneratedQuestion(
                template_id=tpl.id,
                event_id=event.event_id,
                instance_key=player_instance_key(p1),
                question="How many points will Jalen Brunson score in Game 1?",
                answer_options="Under 18||18-22||23-27||28-32||33+",
            ),
        ]
        settings = {"topic_import_id": "nba-test"}
        rows = RowAssembler(settings).assemble_batch(questions, items)
        assert len(rows) == 2
        assert "Brunson" in rows[1].question
        assert "Gilgeous-Alexander" in rows[0].question
