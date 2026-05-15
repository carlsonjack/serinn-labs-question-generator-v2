from __future__ import annotations

from datetime import datetime

from core.config import load_settings
from core.date_rules import QuestionDates, compute_question_dates, get_date_rules_for_category


def test_compute_question_dates_default_rules() -> None:
    settings = load_settings()
    result = compute_question_dates(
        "2026-05-15T21:40:00",
        category_key="mlb",
        settings=settings,
    )
    assert result == QuestionDates(
        start_date="2026-05-14T21:40:00",
        expiration_date="2026-05-15T21:40:00",
        resolution_date="2026-05-16T01:40:00",
    )


def test_category_override_changes_only_resolution() -> None:
    settings = {
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            },
            "mlb": {"resolution_offset_hours": 6},
        }
    }
    result = compute_question_dates(
        "2026-05-15T21:40:00",
        category_key="mlb",
        settings=settings,
    )
    assert result.start_date == "2026-05-14T21:40:00"
    assert result.expiration_date == "2026-05-15T21:40:00"
    assert result.resolution_date == "2026-05-16T03:40:00"


def test_unknown_category_falls_back_to_default() -> None:
    settings = {
        "date_rules": {
            "default": {
                "start_offset_hours": -12,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 2,
            },
        }
    }
    result = compute_question_dates(
        "2026-01-01T12:00:00",
        category_key="unknown_vertical",
        settings=settings,
    )
    assert result == QuestionDates(
        start_date="2026-01-01T00:00:00",
        expiration_date="2026-01-01T12:00:00",
        resolution_date="2026-01-01T14:00:00",
    )


def test_output_has_no_timezone_suffix() -> None:
    result = compute_question_dates(
        "2026-05-15T21:40:00",
        category_key="mlb",
        settings=load_settings(),
    )
    for value in (result.start_date, result.expiration_date, result.resolution_date):
        assert "+" not in value
        assert not value.endswith("Z")
        assert value.count("-") >= 2  # date part has hyphens


def test_parse_event_datetime_accepts_datetime() -> None:
    result = compute_question_dates(
        datetime(2026, 5, 15, 21, 40, 0),
        category_key="mlb",
        settings=load_settings(),
    )
    assert result.expiration_date == "2026-05-15T21:40:00"


def test_get_date_rules_for_category_merges() -> None:
    settings = {
        "date_rules": {
            "default": {"start_offset_hours": -24, "resolution_offset_hours": 4},
            "mlb": {"resolution_offset_hours": 8},
        }
    }
    r = get_date_rules_for_category(settings, "mlb")
    assert r["start_offset_hours"] == -24
    assert r["expiration_offset_hours"] == 0
    assert r["resolution_offset_hours"] == 8
    assert r["resolution_offset_anchor"] == "kickoff"


def test_resolution_offset_anchor_expiration() -> None:
    settings = {
        "date_rules": {
            "default": {
                "start_offset_hours": 0,
                "expiration_offset_hours": 2,
                "resolution_offset_hours": 4,
                "resolution_offset_anchor": "expiration",
            }
        }
    }
    r = compute_question_dates(
        "2026-06-01T12:00:00",
        category_key="any",
        settings=settings,
    )
    assert r.start_date == "2026-06-01T12:00:00"
    assert r.expiration_date == "2026-06-01T14:00:00"
    assert r.resolution_date == "2026-06-01T18:00:00"


def test_resolution_offset_anchor_kickoff_matches_legacy_when_exp_is_zero() -> None:
    settings = {
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
                "resolution_offset_anchor": "kickoff",
            }
        }
    }
    r = compute_question_dates(
        "2026-05-15T21:40:00",
        category_key="mlb",
        settings=settings,
    )
    assert r.resolution_date == "2026-05-16T01:40:00"
