"""Deterministic placeholder filling for sports event templates."""

from __future__ import annotations

import re
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate

_BRACKET_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")
_BRACE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

YES_NO_OPTIONS = "Yes||No"


def event_placeholder_context(
    event: NormalizedEvent,
    template: QuestionTemplate,
) -> dict[str, str]:
    """Build uppercase keys for bracket/brace substitution in event templates."""

    ctx: dict[str, str] = {
        "HOME_TEAM": event.home_team,
        "AWAY_TEAM": event.away_team,
    }
    if event.event_display and str(event.event_display).strip():
        label = str(event.event_display).strip()
        ctx["EVENT_NAME"] = label
        ctx["EVENT"] = label
    if template.line is not None:
        line_str = str(template.line)
        ctx["LINE"] = line_str
        ctx["POINT_TOTAL"] = line_str
    return ctx


def fill_sports_template_text(
    text: str,
    event: NormalizedEvent,
    template: QuestionTemplate,
) -> str:
    """Replace ``[KEY]`` and ``{key}`` placeholders using event + template context."""

    context = event_placeholder_context(event, template)
    lower_ctx: dict[str, str] = {
        "home_team": event.home_team,
        "away_team": event.away_team,
    }
    if event.event_display and str(event.event_display).strip():
        label = str(event.event_display).strip()
        lower_ctx["event_name"] = label
        lower_ctx["event"] = label
    if template.line is not None:
        lower_ctx["line"] = str(template.line)
        lower_ctx["point_total"] = str(template.line)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).upper()
        if key in context:
            return context[key]
        return match.group(0)

    def brace_repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        key_upper = raw.upper()
        if key_upper in context:
            return context[key_upper]
        key_lower = raw.lower()
        if key_lower in lower_ctx:
            return lower_ctx[key_lower]
        return match.group(0)

    out = _BRACKET_PLACEHOLDER_RE.sub(repl, text)
    return _BRACE_PLACEHOLDER_RE.sub(brace_repl, out)


def normalize_yes_no_options(raw: str) -> str:
    """Collapse spaced yes/no variants to ``Yes||No``."""

    collapsed = re.sub(r"\s*\|\|\s*", "||", (raw or "").strip())
    if collapsed.replace(" ", "").lower() in {"yes||no", "yesno"}:
        return YES_NO_OPTIONS
    if not collapsed:
        return YES_NO_OPTIONS
    return collapsed


def resolve_event_answer_options(
    template: QuestionTemplate,
    event: NormalizedEvent,
    players: list[PlayerStatRecord],
) -> str:
    """Build answer_options locally for one template × event (no LLM)."""

    if template.answer_type == "yes_no":
        return normalize_yes_no_options(template.answer_options)

    if template.question_family == "entity_stat":
        if not players:
            raise ValueError(
                f"Entity template {template.id!r} requires players but "
                f"none provided for event {event.event_id}"
            )
        return "||".join(p.player_name for p in players)

    return fill_sports_template_text(template.answer_options, event, template)
