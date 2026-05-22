"""Output row assembly (EPIC 5, Task 5.3).

Combines LLM-generated question text with deterministic fields pulled from
templates, config, and the date rule engine to produce upload-ready output rows.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from core.date_rules import compute_question_dates, parse_event_datetime
from core.input_slots import get_inputs_category_key
from core.parsers.contracts import NormalizedEvent
from core.resolution_date_spec import (
    EventResolutionContext,
    ResolutionDateSpec,
    evaluate_template_datetime_for_event,
)
from core.template_config.schema import QuestionTemplate

from .prompt_builder import GeneratedQuestion, PromptItem

logger = logging.getLogger(__name__)

TOPIC_IMPORT_ID_REQUIRED_MESSAGE = "topic_import_id is required in config but was not set"

OUTPUT_COLUMNS: list[str] = [
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


@dataclass
class OutputRow:
    """One upload-ready row conforming to the client CSV schema."""

    topic_import_id: str
    subcategory: str
    event: str
    question: str
    answer_type: str
    answer_options: str
    start_date: str
    expiration_date: str
    resolution_date: str
    priority: int | str

    def to_dict(self) -> dict[str, Any]:
        """Return an ordered dict matching :data:`OUTPUT_COLUMNS`."""
        d = asdict(self)
        return {col: d[col] for col in OUTPUT_COLUMNS}


def build_event_string(event: NormalizedEvent) -> str:
    """Construct the human-readable event string (e.g. ``'Mets vs Yankees'``).

    When ``event_display`` is set, use it (calendar-style labels); otherwise use
    the head-to-head ``away vs home`` pattern.
    """

    if event.event_display and str(event.event_display).strip():
        return str(event.event_display).strip()
    return f"{event.away_team} vs {event.home_team}"


def resolve_topic_import_id(settings: dict[str, Any], category_key: str | None = None) -> str:
    """Return the topic import ID for this run, or raise if missing.

    Step 6 / ``topic_import_id`` in settings is the source of truth when set.
    ``topic_import_ids.<package>`` is only a fallback when the top-level value
    is empty (e.g. first run before the operator picks an ID).
    """

    explicit = settings.get("topic_import_id", "")
    topic_import_id = str(explicit).strip() if explicit is not None else ""
    if topic_import_id:
        return topic_import_id

    pkg = (category_key if category_key is not None else get_inputs_category_key(settings)).strip().lower()
    topic_ids = settings.get("topic_import_ids")
    if isinstance(topic_ids, dict) and pkg in topic_ids:
        value = topic_ids.get(pkg)
        topic_import_id = str(value).strip() if value is not None else ""
        if topic_import_id:
            return topic_import_id

    raise ValueError(TOPIC_IMPORT_ID_REQUIRED_MESSAGE)


class RowAssembler:
    """Assembles complete output rows from generated questions.

    Parameters
    ----------
    settings:
        Global settings dict (from ``load_settings``).  Used for
        ``topic_import_id`` and passed through to the date rule engine.
    """

    def __init__(self, settings: dict[str, Any], category_key: str | None = None) -> None:
        self.settings = settings
        self.category_key = category_key
        self.topic_import_id: str = str(settings.get("topic_import_id", ""))

    def _resolved_topic_import_id(self) -> str:
        return resolve_topic_import_id(self.settings, self.category_key)

    def assemble(
        self,
        generated: GeneratedQuestion,
        item: PromptItem,
    ) -> OutputRow:
        """Build a single output row from an LLM result and its source item."""
        template = item.template
        event = item.event

        dates = compute_question_dates(
            event.event_datetime,
            category_key=template.subcategory.lower(),
            settings=self.settings,
        )
        # Baseline start/expiration/resolution from YAML date_rules. Optional template
        # specs override in order: start → expiration → resolution. Each step sees
        # question_start / question_expiration updated from prior overrides so anchors
        # chain correctly (expiration may reference the overridden start).
        event_dt = parse_event_datetime(event.event_datetime)
        start_dt = parse_event_datetime(dates.start_date)
        exp_dt = parse_event_datetime(dates.expiration_date)
        meta = dict(event.metadata or {})

        start_date = dates.start_date
        expiration_date = dates.expiration_date
        resolution_date = dates.resolution_date

        raw_start = template.start_date_spec
        if raw_start:
            spec = ResolutionDateSpec.model_validate(raw_start)
            ctx = EventResolutionContext(
                event_datetime=event_dt,
                question_start=start_dt,
                question_expiration=exp_dt,
                metadata=meta,
            )
            override = evaluate_template_datetime_for_event(spec, ctx)
            if override is not None:
                start_date = override.isoformat(timespec="seconds")
                start_dt = override

        raw_exp = template.expiration_date_spec
        if raw_exp:
            spec = ResolutionDateSpec.model_validate(raw_exp)
            ctx = EventResolutionContext(
                event_datetime=event_dt,
                question_start=start_dt,
                question_expiration=exp_dt,
                metadata=meta,
            )
            override = evaluate_template_datetime_for_event(spec, ctx)
            if override is not None:
                expiration_date = override.isoformat(timespec="seconds")
                exp_dt = override

        raw_res = template.resolution_date_spec
        if raw_res:
            spec = ResolutionDateSpec.model_validate(raw_res)
            ctx = EventResolutionContext(
                event_datetime=event_dt,
                question_start=start_dt,
                question_expiration=exp_dt,
                metadata=meta,
            )
            override = evaluate_template_datetime_for_event(spec, ctx)
            if override is not None:
                resolution_date = override.isoformat(timespec="seconds")

        return OutputRow(
            topic_import_id=self._resolved_topic_import_id(),
            subcategory=template.subcategory,
            event=build_event_string(event),
            question=generated.question,
            answer_type=template.answer_type,
            answer_options=generated.answer_options,
            start_date=start_date,
            expiration_date=expiration_date,
            resolution_date=resolution_date,
            priority=template.priority,
        )

    def assemble_batch(
        self,
        generated_questions: list[GeneratedQuestion],
        items: list[PromptItem],
    ) -> list[OutputRow]:
        """Assemble rows for a batch of generated questions.

        ``generated_questions`` and ``items`` are matched by position when
        their ``template_id`` / ``event_id`` pairs align.  When the lists
        arrive pre-matched (same order), positional pairing is used directly.
        When the LLM reorders results, the assembler falls back to key-based
        matching on ``(template_id, event_id)``.
        """
        if not generated_questions:
            return []

        if self._positional_match(generated_questions, items):
            return self._assemble_positional(generated_questions, items)

        return self._assemble_by_key(generated_questions, items)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _positional_match(
        questions: list[GeneratedQuestion],
        items: list[PromptItem],
    ) -> bool:
        if len(questions) != len(items):
            return False
        return all(
            q.template_id == it.template.id and q.event_id == it.event.event_id
            for q, it in zip(questions, items)
        )

    def _assemble_positional(
        self,
        questions: list[GeneratedQuestion],
        items: list[PromptItem],
    ) -> list[OutputRow]:
        return [self.assemble(q, it) for q, it in zip(questions, items)]

    def _assemble_by_key(
        self,
        questions: list[GeneratedQuestion],
        items: list[PromptItem],
    ) -> list[OutputRow]:
        item_map: dict[tuple[str, str], PromptItem] = {
            (it.template.id, it.event.event_id): it for it in items
        }
        rows: list[OutputRow] = []
        for q in questions:
            key = (q.template_id, q.event_id)
            item = item_map.get(key)
            if item is None:
                logger.warning(
                    "No matching PromptItem for generated question "
                    "(template_id=%r, event_id=%r) — skipping row",
                    q.template_id,
                    q.event_id,
                )
                continue
            rows.append(self.assemble(q, item))
        return rows
