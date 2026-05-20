"""Prompt builder for template-driven question generation (EPIC 5, Task 5.1).

Assembles structured prompts from question templates and normalized event data.
The LLM handles natural-language quality (phrasing, grammar, name handling) while
all question types, answer formats, and priority rules come from templates and config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from pydantic import BaseModel

from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate

from .event_fill import fill_sports_template_text, resolve_event_answer_options


# ---------------------------------------------------------------------------
# Prompt configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptConfig:
    """Controls how prompts are assembled.

    ``generation_mode`` is ``"template"`` for Phase 1.  A future
    ``"dynamic"`` mode can be added without restructuring the builder.
    """

    generation_mode: str = "template"


VALID_GENERATION_MODES = frozenset({"template"})


# ---------------------------------------------------------------------------
# Prompt item — one (template × event) work unit
# ---------------------------------------------------------------------------


@dataclass
class PromptItem:
    """A template applied to an event, with optional resolved entity data."""

    template: QuestionTemplate
    event: NormalizedEvent
    players: List[PlayerStatRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pydantic response schemas (for OpenAI structured-output parsing in 5.2)
# ---------------------------------------------------------------------------


class GeneratedQuestion(BaseModel):
    """One generated question row returned by the LLM."""

    template_id: str
    event_id: str
    question: str
    answer_options: str


class GeneratedQuestionBatch(BaseModel):
    """Top-level wrapper so the response is always ``{"questions": [...]}``.

    Used with ``response_format`` / ``chat.completions.parse`` in the batch
    executor (Task 5.2).
    """

    questions: List[GeneratedQuestion]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a structured content generator for a prediction content platform.

MODE: {generation_mode}

Your job is to produce clean, natural-sounding question text and answer \
options for prediction questions. You do NOT invent new question types or \
structures. You ONLY produce output conforming to the supplied templates \
and data.

RULES:
1. Output a JSON object with a "questions" key containing an array of \
question objects — one per input item.
2. Each object must have exactly these fields:
   - "template_id"  — echo the template ID from the input
   - "event_id"     — echo the event ID from the input
   - "question"     — polished, natural-sounding question text
   - "answer_options" — pipe-delimited string (e.g. "Mets||Yankees")
3. Do NOT invent question types or add questions beyond what is requested.
4. Do NOT hallucinate or fabricate entity names, participant names, or statistics.
5. For yes/no questions, answer_options must be exactly "Yes||No".
6. For multiple-choice event questions, use the provided answer option labels.
7. For entity questions, use ONLY the entity names from the \
provided list — do not reorder, rename, or add entities.
8. Make question text grammatically correct and natural-sounding. You may \
rephrase the template for clarity and flow but must not change meaning.
9. Include event context in entity questions so each \
question stands alone without external context.\
"""


# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Assembles OpenAI chat messages from templates + normalized event data.

    Phase 1 (``generation_mode="template"``): the LLM polishes wording
    within template constraints.  Architecture supports a future
    ``"dynamic"`` mode without requiring a rewrite.
    """

    def __init__(self, config: PromptConfig | None = None) -> None:
        self.config = config or PromptConfig()

    @property
    def generation_mode(self) -> str:
        return self.config.generation_mode

    @property
    def response_schema(self) -> type[GeneratedQuestionBatch]:
        """Pydantic model for structured-output parsing (used by 5.2)."""
        return GeneratedQuestionBatch

    # -- public API --------------------------------------------------------

    def build_prompt(self, items: list[PromptItem]) -> list[dict[str, str]]:
        """Build chat messages for a batch of prompt items.

        Returns ``[{"role": "system", ...}, {"role": "user", ...}]``
        suitable for the OpenAI chat-completions API.
        """
        if not items:
            raise ValueError("items must be non-empty")

        return [
            {"role": "system", "content": self._system_message()},
            {"role": "user", "content": self._user_message(items)},
        ]

    def build_single_prompt(self, item: PromptItem) -> list[dict[str, str]]:
        """Convenience wrapper for a single template × event pair."""
        return self.build_prompt([item])

    # -- internals ---------------------------------------------------------

    def _system_message(self) -> str:
        return _SYSTEM_PROMPT.format(generation_mode=self.config.generation_mode)

    def _user_message(self, items: list[PromptItem]) -> str:
        sections: list[str] = [
            f"Generate {len(items)} question(s) from the following inputs.\n",
        ]
        for idx, item in enumerate(items, 1):
            sections.append(self._format_item(idx, item))

        sections.append(
            'Respond with a JSON object containing a "questions" array '
            "with one entry per input item above."
        )
        return "\n".join(sections)

    def _format_item(self, index: int, item: PromptItem) -> str:
        event = item.event
        tpl = item.template
        lines: list[str] = [f"--- Item {index} ---"]

        lines.append(f"Template ID: {tpl.id}")
        lines.append(f"Event ID: {event.event_id}")
        lines.append(f"Content unit: {event.event_display or f'{event.home_team} vs {event.away_team}'}")
        lines.append(f"Event datetime: {event.event_datetime}")
        lines.append(f"Subcategory: {event.subcategory}")

        filled_q = fill_template_placeholders(tpl, event)
        lines.append(f"Question template: {filled_q}")
        lines.append(f"Answer type: {tpl.answer_type}")

        if tpl.line is not None:
            lines.append(f"Line: {tpl.line}")

        if tpl.question_family == "event":
            lines.append(
                f"Answer options: {resolve_event_answer_options(tpl, event, item.players)}"
            )
        elif tpl.question_family == "entity_stat":
            if not item.players:
                raise ValueError(
                    f"Entity template {tpl.id!r} requires players but "
                    f"none provided for event {event.event_id}"
                )
            player_names = [p.player_name for p in item.players]
            lines.append(
                f"Entities (use ONLY these as answer options): {', '.join(player_names)}"
            )
            lines.append(
                f"Answer options: {resolve_event_answer_options(tpl, event, item.players)}"
            )
            lines.append(f"Stat: {tpl.stat_column}")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure helpers (usable outside the class)
# ---------------------------------------------------------------------------


def fill_template_placeholders(
    template: QuestionTemplate,
    event: NormalizedEvent,
) -> str:
    """Replace event placeholders in template question text (bracket and brace forms)."""
    return fill_sports_template_text(template.question, event, template)


def fill_event_answer_options(
    template: QuestionTemplate,
    event: NormalizedEvent,
) -> str:
    """Replace placeholders in ``answer_options`` for event-level templates."""
    return fill_sports_template_text(template.answer_options, event, template)
