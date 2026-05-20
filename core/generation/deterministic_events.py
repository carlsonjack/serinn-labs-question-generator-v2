"""Local (non-LLM) question assembly for sports event templates."""

from __future__ import annotations

from .event_fill import fill_sports_template_text, resolve_event_answer_options
from .prompt_builder import GeneratedQuestion, PromptItem


def build_deterministic_questions(items: list[PromptItem]) -> list[GeneratedQuestion]:
    """Return one :class:`GeneratedQuestion` per item using template fill only."""

    out: list[GeneratedQuestion] = []
    for item in items:
        tpl = item.template
        event = item.event
        out.append(
            GeneratedQuestion(
                template_id=tpl.id,
                event_id=event.event_id,
                question=fill_sports_template_text(tpl.question, event, tpl),
                answer_options=resolve_event_answer_options(
                    tpl, event, item.players
                ),
            )
        )
    return out
