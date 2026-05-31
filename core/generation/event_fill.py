"""Deterministic placeholder filling for sports event templates."""

from __future__ import annotations

import re
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.generation.season_scope import uses_schedule_teams
from core.template_config.schema import QuestionTemplate

_BRACKET_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")
_BRACE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")
_PLAYER_TOKEN_RE = re.compile(
    r"\[PLAYER\]|\{player\}|\[DRIVER\]|\{driver\}|\[GOLFER\]|\{golfer\}",
    re.IGNORECASE,
)
_TEAM_TOKEN_RE = re.compile(r"\[TEAM\]|\{team\}", re.IGNORECASE)
_DRIVER_EVENT_FALLBACK_RE = re.compile(r"\[DRIVER\]|\{driver\}", re.IGNORECASE)

YES_NO_OPTIONS = "Yes||No"
_DRIVER_LITERAL = "driver"


def uses_player_question_expansion(template: QuestionTemplate) -> bool:
    """True when ``entity_stat`` expands one row per player via player/driver tokens."""

    return template.question_family == "entity_stat" and bool(
        _PLAYER_TOKEN_RE.search(template.question or "")
    )


def uses_team_question_expansion(template: QuestionTemplate) -> bool:
    """True when ``event`` expands one row per constructor via ``[TEAM]`` / ``{team}``."""

    return template.question_family == "event" and bool(
        _TEAM_TOKEN_RE.search(template.question or "")
    )


def unique_teams_from_stats(player_stats: list[PlayerStatRecord]) -> list[str]:
    """Sorted unique constructor labels from standings ``TEAM`` column."""

    seen: set[str] = set()
    teams: list[str] = []
    for record in player_stats:
        label = str(record.source_team or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        teams.append(label)
    return sorted(teams, key=str.casefold)


def player_instance_key(player: PlayerStatRecord) -> str:
    """Stable slug for matching expanded player-prop rows."""

    slug = re.sub(r"[^a-z0-9]+", "-", player.player_name.lower()).strip("-")
    return slug or player.player_name


def team_instance_key(team_label: str) -> str:
    """Stable slug for matching expanded team-prop rows."""

    slug = re.sub(r"[^a-z0-9]+", "-", team_label.lower()).strip("-")
    return slug or team_label


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


def _apply_driver_event_fallback(text: str, template: QuestionTemplate) -> str:
    """Replace driver tokens with the word ``driver`` on event templates without a player."""

    if template.question_family != "event":
        return text
    return _DRIVER_EVENT_FALLBACK_RE.sub(_DRIVER_LITERAL, text)


def fill_sports_template_text(
    text: str,
    event: NormalizedEvent,
    template: QuestionTemplate,
    *,
    player: PlayerStatRecord | None = None,
    team: str | None = None,
) -> str:
    """Replace ``[KEY]`` and ``{key}`` placeholders using event + template context."""

    context = event_placeholder_context(event, template)
    lower_ctx: dict[str, str] = {
        "home_team": event.home_team,
        "away_team": event.away_team,
    }
    if player is not None:
        context["PLAYER"] = player.player_name
        context["DRIVER"] = player.player_name
        context["GOLFER"] = player.player_name
        lower_ctx["player"] = player.player_name
        lower_ctx["driver"] = player.player_name
        lower_ctx["golfer"] = player.player_name
    if team is not None and str(team).strip():
        context["TEAM"] = str(team).strip()
        lower_ctx["team"] = str(team).strip()
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
    out = _BRACE_PLACEHOLDER_RE.sub(brace_repl, out)
    if player is None:
        out = _apply_driver_event_fallback(out, template)
    return out


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
    *,
    schedule_teams: list[str] | None = None,
    team: str | None = None,
) -> str:
    """Build answer_options locally for one template × event (no LLM)."""

    if template.answer_type == "yes_no":
        return normalize_yes_no_options(template.answer_options)

    if uses_schedule_teams(template):
        if not schedule_teams:
            raise ValueError(
                f"Template {template.id!r} requires schedule teams but none were provided"
            )
        return "||".join(schedule_teams)

    if template.question_family == "entity_stat":
        if uses_player_question_expansion(template):
            return fill_sports_template_text(
                template.answer_options or "",
                event,
                template,
                player=players[0] if players else None,
            )
        if not players:
            raise ValueError(
                f"Entity template {template.id!r} requires players but "
                f"none provided for event {event.event_id}"
            )
        return "||".join(p.player_name for p in players)

    return fill_sports_template_text(
        template.answer_options or "",
        event,
        template,
        team=team,
    )
