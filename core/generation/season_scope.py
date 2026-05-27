"""Season-scoped sports template helpers (one row per season window)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Sequence

from core.parsers.contracts import NormalizedEvent
from core.template_config.schema import QuestionTemplate

_SCHEDULE_TEAM_PLACEHOLDERS = frozenset({"{schedule_teams}", "{team_options}"})


def is_season_scope(template: QuestionTemplate) -> bool:
    """Return True when the template emits one row for the whole season window."""

    return (template.generation_scope or "event") == "season"


def uses_schedule_teams(template: QuestionTemplate) -> bool:
    """Return True when answer options should list all teams from the schedule."""

    ao = (template.answer_options or "").strip()
    return ao in _SCHEDULE_TEAM_PLACEHOLDERS


def unique_schedule_teams(events: Sequence[NormalizedEvent]) -> list[str]:
    """Sorted, deduplicated team names from schedule home/away columns."""

    seen: set[str] = set()
    teams: list[str] = []
    for event in events:
        for label in (event.home_team, event.away_team):
            name = str(label or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            teams.append(name)
    return sorted(teams, key=str.casefold)


def _season_year(events: Sequence[NormalizedEvent], date_filter: Mapping[str, Any] | None) -> int:
    if date_filter:
        for key in ("end", "start"):
            raw = date_filter.get(key)
            if raw:
                text = str(raw).strip()
                match = re.search(r"(20\d{2})", text)
                if match:
                    return int(match.group(1))
                try:
                    return datetime.fromisoformat(text.replace("Z", "+00:00")).year
                except ValueError:
                    pass
    for event in events:
        raw = str(event.event_datetime or "").strip()
        if len(raw) >= 4 and raw[:4].isdigit():
            return int(raw[:4])
    return datetime.utcnow().year


def build_season_event(
    subcategory: str,
    events: Sequence[NormalizedEvent],
    date_filter: Mapping[str, Any] | None = None,
) -> NormalizedEvent:
    """Synthetic event for season-scoped rows (dates, export event column)."""

    sub = (subcategory or "Season").strip() or "Season"
    year = _season_year(events, date_filter)
    label = f"{sub} {year} Season"
    event_dt = events[0].event_datetime if events else f"{year}-01-01T00:00:00"
    return NormalizedEvent(
        event_id=f"season-{sub.lower().replace(' ', '-')}-{year}",
        home_team="",
        away_team="",
        event_datetime=event_dt,
        subcategory=sub,
        event_display=label,
    )
