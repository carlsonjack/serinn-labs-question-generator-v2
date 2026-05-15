"""Parse human / marketing calendar strings into ``datetime.date`` for content pipelines."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from dateutil.parser import ParserError, parse as parse_datetime

# En dash, em dash, minus sign, hyphen bullet
_UNICODE_DASHES = ("\u2013", "\u2014", "\u2212", "\u2010")

_PREFIX_RE = re.compile(
    r"(?i)^(daily|weekly|monthly|season(?:\s*run)?|limited|special|run)\s*[:-]\s*"
)

_MONTH_WORD = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

_FIRST_CALENDAR_PHRASE = re.compile(
    rf"\b({_MONTH_WORD}\s+\d{{1,2}})(?:\s*,\s*(19\d{{2}}|20\d{{2}}))?\b",
    re.I,
)

_TRAILING_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\s*$")


def sanitize_date_display_text(raw: str) -> str:
    """Normalize dashes and strip common leading schedule labels."""

    s = str(raw or "").strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return ""
    for ch in _UNICODE_DASHES:
        s = s.replace(ch, "-")
    s = _PREFIX_RE.sub("", s)
    return s.strip()


def first_calendar_date_phrase(raw: Any) -> str | None:
    """Pick a ``Month D`` or ``Month D, YYYY`` substring suitable for dateutil."""

    s = sanitize_date_display_text(raw)
    if not s:
        return None
    m = _FIRST_CALENDAR_PHRASE.search(s)
    if not m:
        return None
    phrase = m.group(0).strip()
    if m.group(2) is None:
        y = _TRAILING_YEAR.search(s)
        if y:
            phrase = f"{m.group(1)}, {y.group(1)}"
    return phrase


def parse_entity_calendar_date(raw: Any) -> date:
    """Parse release-style cells; date ranges and ``Daily – …`` use the **start** date."""

    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw is None:
        raise ValueError("empty date value")
    if isinstance(raw, float) and str(raw) == "nan":
        raise ValueError("empty date value")

    phrase = first_calendar_date_phrase(raw)
    if phrase:
        try:
            return parse_datetime(phrase, fuzzy=True).date()
        except (ValueError, TypeError, OverflowError, ParserError):
            pass

    s = sanitize_date_display_text(str(raw))
    if not s:
        raise ValueError("empty date value")
    return parse_datetime(s, fuzzy=True).date()
