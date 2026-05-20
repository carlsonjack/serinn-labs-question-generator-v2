"""Tests for output row assembly (EPIC 5, Task 5.3)."""

from __future__ import annotations

import pytest

from core.date_rules import compute_question_dates
from core.generation.prompt_builder import GeneratedQuestion, PromptItem
from core.generation.row_assembler import (
    OUTPUT_COLUMNS,
    OutputRow,
    RowAssembler,
    build_event_string,
)
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SETTINGS: dict = {
    "topic_import_id": "mlb-regular-season",
    "date_rules": {
        "default": {
            "start_offset_hours": -24,
            "expiration_offset_hours": 0,
            "resolution_offset_hours": 4,
        },
        "mlb": {
            "start_offset_hours": -24,
            "expiration_offset_hours": 0,
            "resolution_offset_hours": 4,
        },
    },
}

EVENT_TEMPLATE = QuestionTemplate(
    id="mlb_game_winner",
    subcategory="MLB",
    question_family="event",
    question="Who will win {home_team} vs {away_team}?",
    answer_type="multiple_choice",
    answer_options="{home_team}||{away_team}",
    priority=1,
    requires_entities=False,
)

YESNO_TEMPLATE = QuestionTemplate(
    id="mlb_win_margin_2",
    subcategory="MLB",
    question_family="event",
    question="Will {home_team} vs {away_team} be decided by more than 2 runs?",
    answer_type="yes_no",
    answer_options="Yes||No",
    priority="",
    requires_entities=False,
)

ENTITY_TEMPLATE = QuestionTemplate(
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

EVENT_A = NormalizedEvent(
    event_id="MLB000657",
    home_team="Athletics",
    away_team="Giants",
    event_datetime="2026-05-15T21:40:00",
    subcategory="MLB",
)

EVENT_B = NormalizedEvent(
    event_id="MLB000700",
    home_team="Yankees",
    away_team="Mets",
    event_datetime="2026-05-16T19:10:00",
    subcategory="MLB",
)


def _gen_q(
    template_id: str = "mlb_game_winner",
    event_id: str = "MLB000657",
    question: str = "Who will win Giants vs Athletics?",
    answer_options: str = "Athletics||Giants",
) -> GeneratedQuestion:
    return GeneratedQuestion(
        template_id=template_id,
        event_id=event_id,
        question=question,
        answer_options=answer_options,
    )


def _item(
    template: QuestionTemplate | None = None,
    event: NormalizedEvent | None = None,
    players: list[PlayerStatRecord] | None = None,
) -> PromptItem:
    return PromptItem(
        template=template or EVENT_TEMPLATE,
        event=event or EVENT_A,
        players=players or [],
    )


# ---------------------------------------------------------------------------
# TestBuildEventString
# ---------------------------------------------------------------------------


class TestBuildEventString:
    def test_standard_matchup(self):
        assert build_event_string(EVENT_A) == "Giants vs Athletics"

    def test_different_teams(self):
        assert build_event_string(EVENT_B) == "Mets vs Yankees"

    def test_event_display_overrides(self):
        ev = NormalizedEvent(
            event_id="x",
            home_team="H",
            away_team="A",
            event_datetime="2026-03-08T14:00:00",
            subcategory="F1",
            event_display="Australian Grand Prix - Race",
        )
        assert build_event_string(ev) == "Australian Grand Prix - Race"


# ---------------------------------------------------------------------------
# TestOutputRow
# ---------------------------------------------------------------------------


class TestOutputRow:
    def test_to_dict_returns_all_columns(self):
        row = OutputRow(
            topic_import_id="C1",
            subcategory="MLB",
            event="Giants vs Athletics",
            question="Who wins?",
            answer_type="multiple_choice",
            answer_options="Athletics||Giants",
            start_date="2026-05-14T21:40:00",
            expiration_date="2026-05-15T21:40:00",
            resolution_date="2026-05-16T01:40:00",
            priority=1,
        )
        d = row.to_dict()
        assert list(d.keys()) == OUTPUT_COLUMNS

    def test_to_dict_values_match(self):
        row = OutputRow(
            topic_import_id="C1",
            subcategory="MLB",
            event="Giants vs Athletics",
            question="Who wins?",
            answer_type="multiple_choice",
            answer_options="Athletics||Giants",
            start_date="2026-05-14T21:40:00",
            expiration_date="2026-05-15T21:40:00",
            resolution_date="2026-05-16T01:40:00",
            priority=1,
        )
        d = row.to_dict()
        assert d["topic_import_id"] == "C1"
        assert d["subcategory"] == "MLB"
        assert d["priority"] == 1


class TestOutputColumns:
    def test_column_count(self):
        assert len(OUTPUT_COLUMNS) == 10

    def test_column_names(self):
        expected = [
            "topic_import_id",
            "subcategory",
            "event",
            "question",
            "answer_type",
            "answer_options",
            "start_date",
            "expiration_date",
            "resolution_date",
            "priority",
        ]
        assert OUTPUT_COLUMNS == expected


# ---------------------------------------------------------------------------
# TestRowAssemblerSingle
# ---------------------------------------------------------------------------


class TestRowAssemblerSingle:
    """Tests for ``RowAssembler.assemble`` (single row)."""

    def setup_method(self):
        self.assembler = RowAssembler(SETTINGS)

    def test_topic_import_id_from_settings(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.topic_import_id == "mlb-regular-season"

    def test_topic_import_ids_override_per_package(self):
        settings = {
            **SETTINGS,
            "inputs": {
                "category_key": "f1",
                "files": {"f1": {"schedule": "x.xlsx"}},
            },
            "topic_import_ids": {"f1": "f1-race-winner"},
        }
        assembler = RowAssembler(settings)
        row = assembler.assemble(_gen_q(), _item())
        assert row.topic_import_id == "f1-race-winner"

    def test_topic_import_id_missing_raises_clear_error(self):
        assembler = RowAssembler({})
        with pytest.raises(ValueError, match="topic_import_id is required in config but was not set"):
            assembler.assemble(_gen_q(), _item())

    def test_topic_import_id_whitespace_raises_clear_error(self):
        assembler = RowAssembler({"topic_import_id": "   "})
        with pytest.raises(ValueError, match="topic_import_id is required in config but was not set"):
            assembler.assemble(_gen_q(), _item())

    def test_subcategory_from_template(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.subcategory == "MLB"

    def test_event_string_constructed(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.event == "Giants vs Athletics"

    def test_question_from_llm(self):
        q = _gen_q(question="Who will emerge victorious, Giants or Athletics?")
        row = self.assembler.assemble(q, _item())
        assert row.question == "Who will emerge victorious, Giants or Athletics?"

    def test_answer_type_from_template(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.answer_type == "multiple_choice"

    def test_answer_type_yes_no(self):
        q = _gen_q(
            template_id="mlb_win_margin_2",
            question="Will the game be decided by more than 2 runs?",
            answer_options="Yes||No",
        )
        item = _item(template=YESNO_TEMPLATE)
        row = self.assembler.assemble(q, item)
        assert row.answer_type == "yes_no"

    def test_answer_options_from_llm(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.answer_options == "Athletics||Giants"

    def test_answer_options_entity(self):
        q = _gen_q(
            template_id="mlb_home_run",
            question="Who will hit a home run in Giants vs Athletics?",
            answer_options="Mike Trout||Shohei Ohtani||Aaron Judge||Mookie Betts",
        )
        players = [
            PlayerStatRecord("Mike Trout", "LAA", "LAA", {"HR": 30.0}, None, 1),
            PlayerStatRecord("Shohei Ohtani", "LAD", "LAD", {"HR": 40.0}, None, 2),
        ]
        item = _item(template=ENTITY_TEMPLATE, players=players)
        row = self.assembler.assemble(q, item)
        assert "Mike Trout" in row.answer_options
        assert "Shohei Ohtani" in row.answer_options

    def test_priority_integer(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.priority == 1

    def test_priority_blank(self):
        q = _gen_q(
            template_id="mlb_win_margin_2",
            question="Will the game be decided by more than 2 runs?",
            answer_options="Yes||No",
        )
        item = _item(template=YESNO_TEMPLATE)
        row = self.assembler.assemble(q, item)
        assert row.priority == ""


# ---------------------------------------------------------------------------
# TestDateComputation
# ---------------------------------------------------------------------------


class TestDateComputation:
    """Verify the assembler correctly delegates to the date rule engine."""

    def setup_method(self):
        self.assembler = RowAssembler(SETTINGS)

    def test_start_date_minus_24h(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.start_date == "2026-05-14T21:40:00"

    def test_expiration_date_equals_event(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.expiration_date == "2026-05-15T21:40:00"

    def test_resolution_date_plus_4h(self):
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.resolution_date == "2026-05-16T01:40:00"

    def test_resolution_date_spec_overrides_yaml_only(self):
        tpl = QuestionTemplate(
            id="mlb_game_winner",
            subcategory="MLB",
            question_family="event",
            question="Who will win {home_team} vs {away_team}?",
            answer_type="multiple_choice",
            answer_options="{home_team}||{away_team}",
            priority=1,
            requires_entities=False,
            resolution_date_spec={
                "kind": "offset_from_anchor",
                "anchor": "event_datetime",
                "offset_days": 0,
                "offset_hours": 6,
            },
        )
        row = self.assembler.assemble(_gen_q(), _item(template=tpl))
        assert row.start_date == "2026-05-14T21:40:00"
        assert row.expiration_date == "2026-05-15T21:40:00"
        assert row.resolution_date == "2026-05-16T03:40:00"

    def test_start_date_spec_event_minus_hours(self):
        tpl = QuestionTemplate(
            id="mlb_game_winner",
            subcategory="MLB",
            question_family="event",
            question="Who will win {home_team} vs {away_team}?",
            answer_type="multiple_choice",
            answer_options="{home_team}||{away_team}",
            priority=1,
            requires_entities=False,
            start_date_spec={
                "kind": "offset_from_anchor",
                "anchor": "event_datetime",
                "offset_days": 0,
                "offset_hours": -48,
            },
        )
        row = self.assembler.assemble(_gen_q(), _item(template=tpl))
        assert row.start_date == "2026-05-13T21:40:00"
        assert row.expiration_date == "2026-05-15T21:40:00"
        assert row.resolution_date == "2026-05-16T01:40:00"

    def test_expiration_spec_sees_overridden_start(self):
        tpl = QuestionTemplate(
            id="mlb_game_winner",
            subcategory="MLB",
            question_family="event",
            question="Who will win {home_team} vs {away_team}?",
            answer_type="multiple_choice",
            answer_options="{home_team}||{away_team}",
            priority=1,
            requires_entities=False,
            start_date_spec={
                "kind": "offset_from_anchor",
                "anchor": "event_datetime",
                "offset_days": 0,
                "offset_hours": -48,
            },
            expiration_date_spec={
                "kind": "offset_from_anchor",
                "anchor": "question_start",
                "offset_days": 0,
                "offset_hours": 24,
            },
        )
        row = self.assembler.assemble(_gen_q(), _item(template=tpl))
        assert row.start_date == "2026-05-13T21:40:00"
        assert row.expiration_date == "2026-05-14T21:40:00"
        assert row.resolution_date == "2026-05-16T01:40:00"

    def test_dates_match_engine_directly(self):
        dates = compute_question_dates(
            "2026-05-15T21:40:00",
            category_key="mlb",
            settings=SETTINGS,
        )
        row = self.assembler.assemble(_gen_q(), _item())
        assert row.start_date == dates.start_date
        assert row.expiration_date == dates.expiration_date
        assert row.resolution_date == dates.resolution_date

    def test_different_event_datetime(self):
        q = _gen_q(event_id="MLB000700")
        item = _item(event=EVENT_B)
        row = self.assembler.assemble(q, item)
        assert row.start_date == "2026-05-15T19:10:00"
        assert row.expiration_date == "2026-05-16T19:10:00"
        assert row.resolution_date == "2026-05-16T23:10:00"

    def test_uses_subcategory_as_category_key(self):
        """The assembler lowercases the template subcategory for the date engine."""
        row = self.assembler.assemble(_gen_q(), _item())
        expected = compute_question_dates(
            "2026-05-15T21:40:00",
            category_key="mlb",
            settings=SETTINGS,
        )
        assert row.start_date == expected.start_date


# ---------------------------------------------------------------------------
# TestAssembleBatch
# ---------------------------------------------------------------------------


class TestAssembleBatch:
    """Tests for ``RowAssembler.assemble_batch``."""

    def setup_method(self):
        self.assembler = RowAssembler(SETTINGS)

    def test_empty_returns_empty(self):
        assert self.assembler.assemble_batch([], []) == []

    def test_positional_match_single(self):
        rows = self.assembler.assemble_batch([_gen_q()], [_item()])
        assert len(rows) == 1
        assert rows[0].event == "Giants vs Athletics"

    def test_positional_match_multiple(self):
        q1 = _gen_q()
        q2 = _gen_q(
            template_id="mlb_game_winner",
            event_id="MLB000700",
            question="Who will win Mets vs Yankees?",
            answer_options="Yankees||Mets",
        )
        items = [_item(), _item(event=EVENT_B)]
        rows = self.assembler.assemble_batch([q1, q2], items)
        assert len(rows) == 2
        assert rows[0].event == "Giants vs Athletics"
        assert rows[1].event == "Mets vs Yankees"

    def test_key_based_match_reordered(self):
        """LLM returned questions in a different order than items."""
        q1 = _gen_q(
            template_id="mlb_game_winner",
            event_id="MLB000700",
            question="Who will win Mets vs Yankees?",
            answer_options="Yankees||Mets",
        )
        q2 = _gen_q()
        items = [_item(), _item(event=EVENT_B)]
        rows = self.assembler.assemble_batch([q1, q2], items)
        assert len(rows) == 2
        assert rows[0].event == "Mets vs Yankees"
        assert rows[1].event == "Giants vs Athletics"

    def test_key_mismatch_skips_unknown(self):
        """A generated question with no matching item is skipped with a warning."""
        q_unknown = _gen_q(
            template_id="unknown_tpl",
            event_id="UNKNOWN",
            question="???",
            answer_options="A||B",
        )
        rows = self.assembler.assemble_batch([q_unknown], [_item()])
        assert len(rows) == 0

    def test_mixed_templates_in_batch(self):
        q1 = _gen_q()
        q2 = _gen_q(
            template_id="mlb_win_margin_2",
            event_id="MLB000657",
            question="Will the game be decided by more than 2 runs?",
            answer_options="Yes||No",
        )
        items = [
            _item(),
            _item(template=YESNO_TEMPLATE),
        ]
        rows = self.assembler.assemble_batch([q1, q2], items)
        assert len(rows) == 2
        assert rows[0].answer_type == "multiple_choice"
        assert rows[1].answer_type == "yes_no"


# ---------------------------------------------------------------------------
# TestRowAssemblerInit
# ---------------------------------------------------------------------------


class TestRowAssemblerInit:
    def test_reads_topic_import_id(self):
        assembler = RowAssembler({"topic_import_id": "XYZ"})
        assert assembler.topic_import_id == "XYZ"

    def test_missing_topic_import_id_defaults_empty_until_resolved(self):
        assembler = RowAssembler({})
        assert assembler.topic_import_id == ""

    def test_settings_stored(self):
        assembler = RowAssembler(SETTINGS)
        assert assembler.settings is SETTINGS


# ---------------------------------------------------------------------------
# TestEndToEndRow
# ---------------------------------------------------------------------------


class TestEndToEndRow:
    """Full round-trip: every field of the output row is set correctly."""

    def test_full_event_row(self):
        assembler = RowAssembler(SETTINGS)
        q = _gen_q(
            question="Who will emerge victorious when the Giants face the Athletics?",
            answer_options="Athletics||Giants",
        )
        row = assembler.assemble(q, _item())
        d = row.to_dict()
        assert d == {
            "topic_import_id": "mlb-regular-season",
            "subcategory": "MLB",
            "event": "Giants vs Athletics",
            "question": "Who will emerge victorious when the Giants face the Athletics?",
            "answer_type": "multiple_choice",
            "answer_options": "Athletics||Giants",
            "start_date": "2026-05-14T21:40:00",
            "expiration_date": "2026-05-15T21:40:00",
            "resolution_date": "2026-05-16T01:40:00",
            "priority": 1,
        }

    def test_full_yesno_row(self):
        assembler = RowAssembler(SETTINGS)
        q = _gen_q(
            template_id="mlb_win_margin_2",
            question="Will the Athletics defeat the Giants by more than 2 runs?",
            answer_options="Yes||No",
        )
        item = _item(template=YESNO_TEMPLATE)
        row = assembler.assemble(q, item)
        d = row.to_dict()
        assert d["answer_type"] == "yes_no"
        assert d["answer_options"] == "Yes||No"
        assert d["priority"] == ""

    def test_full_entity_row(self):
        assembler = RowAssembler(SETTINGS)
        q = _gen_q(
            template_id="mlb_home_run",
            question="Who will hit a home run in Giants vs Athletics?",
            answer_options="Mike Trout||Aaron Judge",
        )
        players = [
            PlayerStatRecord("Mike Trout", "LAA", "LAA", {"HR": 30.0}, None, 1),
            PlayerStatRecord("Aaron Judge", "NYY", "NYY", {"HR": 45.0}, None, 2),
        ]
        item = _item(template=ENTITY_TEMPLATE, players=players)
        row = assembler.assemble(q, item)
        d = row.to_dict()
        assert d["answer_type"] == "multiple_choice"
        assert d["answer_options"] == "Mike Trout||Aaron Judge"
        assert d["priority"] == ""
        assert d["subcategory"] == "MLB"
