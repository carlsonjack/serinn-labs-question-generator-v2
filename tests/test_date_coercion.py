"""Tests for flexible calendar / release date string parsing."""

from __future__ import annotations

from datetime import date

import pytest

from core.date_coercion import first_calendar_date_phrase, parse_entity_calendar_date


def test_parse_daily_range_with_unicode_dashes() -> None:
    raw = "Daily \u2013 Jun 11\u2013Jul 19, 2026"
    assert parse_entity_calendar_date(raw) == date(2026, 6, 11)
    assert first_calendar_date_phrase(raw) == "Jun 11, 2026"


def test_parse_plain_us_date() -> None:
    assert parse_entity_calendar_date("June 4, 2026") == date(2026, 6, 4)


def test_parse_iso_date() -> None:
    assert parse_entity_calendar_date("2026-06-04") == date(2026, 6, 4)


def test_parse_ascii_daily_prefix_range() -> None:
    assert parse_entity_calendar_date("Daily - Jun 11-Jul 19, 2026") == date(2026, 6, 11)


def test_parse_weekly_prefix() -> None:
    assert parse_entity_calendar_date("Weekly: Jul 1-Aug 15, 2026") == date(2026, 7, 1)


def test_parse_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_entity_calendar_date("")
