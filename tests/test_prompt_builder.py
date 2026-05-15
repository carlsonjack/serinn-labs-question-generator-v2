"""Tests for the prompt builder (EPIC 5, Task 5.1)."""

from __future__ import annotations

import json

import pytest

from core.generation.prompt_builder import (
    GeneratedQuestion,
    GeneratedQuestionBatch,
    PromptBuilder,
    PromptConfig,
    PromptItem,
    fill_event_answer_options,
    fill_template_placeholders,
)
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _event(
    event_id: str = "MLB000657",
    home_team: str = "Athletics",
    away_team: str = "Giants",
    event_datetime: str = "2026-05-15T21:40:00",
    subcategory: str = "MLB",
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        event_datetime=event_datetime,
        subcategory=subcategory,
    )


def _game_winner_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="mlb_game_winner",
        subcategory="MLB",
        question_family="event",
        question="Who will win {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{home_team}||{away_team}",
        priority=1,
        requires_entities=False,
    )


def _yes_no_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="mlb_win_margin_2",
        subcategory="MLB",
        question_family="event",
        question="Will {home_team} vs {away_team} be decided by more than 2 runs?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
    )


def _line_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="mlb_total_runs_over_8_5",
        subcategory="MLB",
        question_family="event",
        question="Will total runs in {home_team} vs {away_team} exceed {line}?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
        line=8.5,
    )


def _entity_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="mlb_home_run",
        subcategory="MLB",
        question_family="entity_stat",
        question="Who will hit a home run?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority="",
        requires_entities=True,
        stat_column="HR",
        top_n_per_team=2,
    )


def _players() -> list[PlayerStatRecord]:
    return [
        PlayerStatRecord(
            player_name="Aaron Judge",
            team="NYY",
            source_team="Yankees",
            stat_values={"HR": 40, "RBI": 100},
            source_sheet="2026",
            row_number=1,
        ),
        PlayerStatRecord(
            player_name="Pete Alonso",
            team="NYM",
            source_team="Mets",
            stat_values={"HR": 35, "RBI": 90},
            source_sheet="2026",
            row_number=2,
        ),
    ]


# ---------------------------------------------------------------------------
# PromptConfig defaults
# ---------------------------------------------------------------------------


class TestPromptConfig:
    def test_default_generation_mode(self):
        cfg = PromptConfig()
        assert cfg.generation_mode == "template"

    def test_custom_generation_mode(self):
        cfg = PromptConfig(generation_mode="dynamic")
        assert cfg.generation_mode == "dynamic"

    def test_frozen(self):
        cfg = PromptConfig()
        with pytest.raises(AttributeError):
            cfg.generation_mode = "dynamic"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# fill_template_placeholders
# ---------------------------------------------------------------------------


class TestFillTemplatePlaceholders:
    def test_event_home_away(self):
        result = fill_template_placeholders(_game_winner_template(), _event())
        assert result == "Who will win Athletics vs Giants?"

    def test_line_placeholder(self):
        result = fill_template_placeholders(_line_template(), _event())
        assert result == "Will total runs in Athletics vs Giants exceed 8.5?"

    def test_no_line_leaves_text_unchanged(self):
        tpl = _yes_no_template()
        result = fill_template_placeholders(tpl, _event())
        assert "{line}" not in result
        assert "Athletics" in result and "Giants" in result


# ---------------------------------------------------------------------------
# fill_event_answer_options
# ---------------------------------------------------------------------------


class TestFillEventAnswerOptions:
    def test_team_options(self):
        result = fill_event_answer_options(_game_winner_template(), _event())
        assert result == "Athletics||Giants"

    def test_yes_no_unchanged(self):
        result = fill_event_answer_options(_yes_no_template(), _event())
        assert result == "Yes||No"


# ---------------------------------------------------------------------------
# PromptBuilder — structure
# ---------------------------------------------------------------------------


class TestPromptBuilderStructure:
    def test_returns_two_messages(self):
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        msgs = builder.build_prompt([item])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_system_message_contains_mode(self):
        builder = PromptBuilder(PromptConfig(generation_mode="template"))
        item = PromptItem(template=_game_winner_template(), event=_event())
        msgs = builder.build_prompt([item])
        assert "MODE: template" in msgs[0]["content"]

    def test_custom_mode_in_system(self):
        builder = PromptBuilder(PromptConfig(generation_mode="dynamic"))
        item = PromptItem(template=_game_winner_template(), event=_event())
        msgs = builder.build_prompt([item])
        assert "MODE: dynamic" in msgs[0]["content"]

    def test_generation_mode_property(self):
        builder = PromptBuilder(PromptConfig(generation_mode="template"))
        assert builder.generation_mode == "template"

    def test_response_schema_is_batch_model(self):
        builder = PromptBuilder()
        assert builder.response_schema is GeneratedQuestionBatch

    def test_empty_items_raises(self):
        builder = PromptBuilder()
        with pytest.raises(ValueError, match="non-empty"):
            builder.build_prompt([])

    def test_build_single_prompt_wraps_item(self):
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        msgs = builder.build_single_prompt(item)
        assert len(msgs) == 2
        assert "Item 1" in msgs[1]["content"]


class TestPromptTemplateEvalInvariants:
    """Offline evals for prompt/template safety as new verticals are added."""

    def test_event_prompt_resolves_placeholders_and_preserves_allowed_options(self):
        item = PromptItem(template=_game_winner_template(), event=_event())
        user_msg = PromptBuilder().build_prompt([item])[1]["content"]

        assert "{home_team}" not in user_msg
        assert "{away_team}" not in user_msg
        assert "Template ID: mlb_game_winner" in user_msg
        assert "Event ID: MLB000657" in user_msg
        assert "Answer options: Athletics||Giants" in user_msg

    def test_entity_prompt_lists_only_supplied_players(self):
        item = PromptItem(template=_entity_template(), event=_event(), players=_players())
        user_msg = PromptBuilder().build_prompt([item])[1]["content"]

        assert "Entities (use ONLY these as answer options): Aaron Judge, Pete Alonso" in user_msg
        assert "{entity_options}" not in user_msg
        assert "Stat: HR" in user_msg

    def test_yes_no_prompt_keeps_fixed_answer_options(self):
        item = PromptItem(template=_yes_no_template(), event=_event())
        user_msg = PromptBuilder().build_prompt([item])[1]["content"]

        assert "Answer type: yes_no" in user_msg
        assert "Answer options: Yes||No" in user_msg


# ---------------------------------------------------------------------------
# PromptBuilder — event-level templates
# ---------------------------------------------------------------------------


class TestEventPrompt:
    def test_contains_event_data(self):
        builder = PromptBuilder()
        event = _event()
        item = PromptItem(template=_game_winner_template(), event=event)
        user_msg = builder.build_prompt([item])[1]["content"]

        assert event.event_id in user_msg
        assert event.home_team in user_msg
        assert event.away_team in user_msg
        assert event.event_datetime in user_msg

    def test_contains_filled_question(self):
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Who will win Athletics vs Giants?" in user_msg

    def test_contains_answer_options(self):
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Athletics||Giants" in user_msg

    def test_yes_no_options(self):
        builder = PromptBuilder()
        item = PromptItem(template=_yes_no_template(), event=_event())
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Yes||No" in user_msg

    def test_line_value_in_prompt(self):
        builder = PromptBuilder()
        item = PromptItem(template=_line_template(), event=_event())
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Line: 8.5" in user_msg
        assert "exceed 8.5" in user_msg

    def test_template_id_in_prompt(self):
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "mlb_game_winner" in user_msg


# ---------------------------------------------------------------------------
# PromptBuilder — entity templates
# ---------------------------------------------------------------------------


class TestEntityPrompt:
    def test_player_names_in_prompt(self):
        builder = PromptBuilder()
        item = PromptItem(
            template=_entity_template(), event=_event(), players=_players()
        )
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Aaron Judge" in user_msg
        assert "Pete Alonso" in user_msg

    def test_stat_column_in_prompt(self):
        builder = PromptBuilder()
        item = PromptItem(
            template=_entity_template(), event=_event(), players=_players()
        )
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "Stat: HR" in user_msg

    def test_entity_template_without_players_raises(self):
        builder = PromptBuilder()
        item = PromptItem(template=_entity_template(), event=_event(), players=[])
        with pytest.raises(ValueError, match="requires players"):
            builder.build_prompt([item])

    def test_only_these_directive(self):
        builder = PromptBuilder()
        item = PromptItem(
            template=_entity_template(), event=_event(), players=_players()
        )
        user_msg = builder.build_prompt([item])[1]["content"]
        assert "use ONLY these as answer options" in user_msg


# ---------------------------------------------------------------------------
# PromptBuilder — batch (multiple items)
# ---------------------------------------------------------------------------


class TestBatchPrompt:
    def test_multiple_items_numbered(self):
        builder = PromptBuilder()
        items = [
            PromptItem(template=_game_winner_template(), event=_event()),
            PromptItem(template=_yes_no_template(), event=_event()),
        ]
        user_msg = builder.build_prompt(items)[1]["content"]
        assert "Item 1" in user_msg
        assert "Item 2" in user_msg

    def test_item_count_in_header(self):
        builder = PromptBuilder()
        items = [
            PromptItem(template=_game_winner_template(), event=_event()),
            PromptItem(
                template=_entity_template(), event=_event(), players=_players()
            ),
            PromptItem(template=_line_template(), event=_event()),
        ]
        user_msg = builder.build_prompt(items)[1]["content"]
        assert "Generate 3 question(s)" in user_msg

    def test_mixed_event_and_entity(self):
        builder = PromptBuilder()
        items = [
            PromptItem(template=_game_winner_template(), event=_event()),
            PromptItem(
                template=_entity_template(), event=_event(), players=_players()
            ),
        ]
        user_msg = builder.build_prompt(items)[1]["content"]
        assert "Athletics||Giants" in user_msg
        assert "Aaron Judge" in user_msg


# ---------------------------------------------------------------------------
# System prompt contract enforcement
# ---------------------------------------------------------------------------


class TestSystemPromptContract:
    """Verify the system prompt contains the key constraints from the spec."""

    def _system(self) -> str:
        builder = PromptBuilder()
        item = PromptItem(template=_game_winner_template(), event=_event())
        return builder.build_prompt([item])[0]["content"]

    def test_json_output_instruction(self):
        assert '"questions"' in self._system()

    def test_no_invent_types(self):
        sys = self._system().lower()
        assert "do not invent" in sys

    def test_no_hallucinate(self):
        sys = self._system().lower()
        assert "do not hallucinate" in sys

    def test_entity_exact_match(self):
        sys = self._system()
        assert "ONLY the entity names" in sys


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class TestResponseSchemas:
    def test_generated_question_round_trip(self):
        q = GeneratedQuestion(
            template_id="mlb_game_winner",
            event_id="MLB000657",
            question="Who will win: Athletics or Giants?",
            answer_options="Athletics||Giants",
        )
        data = q.model_dump()
        assert data["template_id"] == "mlb_game_winner"
        rebuilt = GeneratedQuestion.model_validate(data)
        assert rebuilt == q

    def test_batch_parses_json(self):
        raw = {
            "questions": [
                {
                    "template_id": "mlb_game_winner",
                    "event_id": "MLB000657",
                    "question": "Who will win: Athletics or Giants?",
                    "answer_options": "Athletics||Giants",
                }
            ]
        }
        batch = GeneratedQuestionBatch.model_validate(raw)
        assert len(batch.questions) == 1
        assert batch.questions[0].event_id == "MLB000657"

    def test_batch_json_schema_has_questions_key(self):
        schema = GeneratedQuestionBatch.model_json_schema()
        assert "questions" in schema.get("properties", {})
