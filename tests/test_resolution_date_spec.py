"""Unit tests for resolution_date_spec compile helpers and evaluators."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest

from core.resolution_date_spec import (
    ContentResolutionContext,
    EventResolutionContext,
    ResolutionDateSpec,
    compile_resolution_rules_batch_openai,
    compute_resolution_date_for_content,
    compute_resolution_datetime_for_event,
    maybe_compile_resolution_for_template_data,
    parse_resolution_date_spec_dict,
)


def test_parse_spec_roundtrip() -> None:
    raw = {
        "kind": "offset_from_anchor",
        "anchor": "release_date",
        "offset_days": 7,
        "offset_hours": 0,
    }
    spec = parse_resolution_date_spec_dict(raw)
    assert spec is not None
    assert spec.kind == "offset_from_anchor"


def test_content_offset_from_release() -> None:
    spec = ResolutionDateSpec(kind="offset_from_anchor", anchor="release_date", offset_days=4)
    rd = date(2026, 6, 10)
    ctx = ContentResolutionContext(
        release_date=rd,
        question_start=datetime.combine(rd - timedelta(days=7), time.min),
        question_expiration=datetime.combine(rd - timedelta(days=1), time.min),
        metadata={},
    )
    out = compute_resolution_date_for_content(spec, ctx)
    assert out == date(2026, 6, 14)


def test_content_calendar_year_policy() -> None:
    spec = ResolutionDateSpec(
        kind="calendar_in_year",
        calendar_month=11,
        calendar_day=1,
        year_policy="release_year_plus_1",
    )
    rd = date(2025, 3, 1)
    ctx = ContentResolutionContext(
        release_date=rd,
        question_start=datetime.combine(rd, time.min),
        question_expiration=datetime.combine(rd, time.min),
        metadata={},
    )
    assert compute_resolution_date_for_content(spec, ctx) == date(2026, 11, 1)


def test_content_none_falls_through() -> None:
    spec = ResolutionDateSpec(kind="none")
    ctx = ContentResolutionContext(
        release_date=date(2026, 1, 1),
        question_start=datetime.combine(date(2025, 12, 25), time.min),
        question_expiration=datetime.combine(date(2025, 12, 31), time.min),
        metadata={},
    )
    assert compute_resolution_date_for_content(spec, ctx) is None
    assert compute_resolution_date_for_content(None, ctx) is None


def test_event_offset_hours() -> None:
    spec = ResolutionDateSpec(
        kind="offset_from_anchor",
        anchor="event_datetime",
        offset_days=0,
        offset_hours=6,
    )
    base = datetime(2026, 5, 15, 19, 0, 0)
    ctx = EventResolutionContext(
        event_datetime=base,
        question_start=base + timedelta(hours=-24),
        question_expiration=base,
        metadata={},
    )
    out = compute_resolution_datetime_for_event(spec, ctx)
    assert out == base + timedelta(hours=6)


def test_event_resolution_at_expiration_anchor() -> None:
    spec = ResolutionDateSpec(
        kind="offset_from_anchor",
        anchor="question_expiration",
        offset_days=0,
        offset_hours=2,
    )
    base = datetime(2026, 5, 15, 19, 0, 0)
    exp = datetime(2026, 5, 15, 23, 0, 0)
    ctx = EventResolutionContext(
        event_datetime=base,
        question_start=base + timedelta(hours=-24),
        question_expiration=exp,
        metadata={},
    )
    out = compute_resolution_datetime_for_event(spec, ctx)
    assert out == exp + timedelta(hours=2)


def test_window_end_content() -> None:
    spec = ResolutionDateSpec(
        kind="window_end",
        anchor="release_date",
        end_offset_days=14,
    )
    rd = date(2026, 1, 1)
    ctx = ContentResolutionContext(
        release_date=rd,
        question_start=datetime.combine(rd, time.min),
        question_expiration=datetime.combine(rd, time.min),
        metadata={},
    )
    assert compute_resolution_date_for_content(spec, ctx) == date(2026, 1, 15)


def test_metadata_date_from_entity_metadata() -> None:
    spec = ResolutionDateSpec(kind="metadata_date", metadata_key="estimated_nomination_date")
    rd = date(2026, 6, 1)
    ctx = ContentResolutionContext(
        release_date=rd,
        question_start=datetime.combine(rd, time.min),
        question_expiration=datetime.combine(rd, time.min),
        metadata={"estimated_nomination_date": "2026-12-01"},
    )
    assert compute_resolution_date_for_content(spec, ctx) == date(2026, 12, 1)


def test_offset_rejects_invalid_content_anchor() -> None:
    spec = ResolutionDateSpec(
        kind="offset_from_anchor",
        anchor="event_datetime",
        offset_days=1,
    )
    ctx = ContentResolutionContext(
        release_date=date(2026, 1, 1),
        question_start=datetime.combine(date(2025, 12, 25), time.min),
        question_expiration=datetime.combine(date(2025, 12, 31), time.min),
        metadata={},
    )
    assert compute_resolution_date_for_content(spec, ctx) is None


def test_window_end_requires_end_offset() -> None:
    with pytest.raises(ValueError, match="end_offset_days"):
        ResolutionDateSpec(kind="window_end", anchor="release_date")


def _fake_openai_completion_json(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(payload)
    msg.refusal = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def test_compile_resolution_rules_batch_openai_with_mock_client() -> None:
    """compile_resolution_rules_batch_openai delegates to client; no network."""
    batch_json = {
        "items": [
            {
                "template_id": "evt-1",
                "spec": {
                    "kind": "offset_from_anchor",
                    "anchor": "event_datetime",
                    "offset_days": 0,
                    "offset_hours": 2,
                },
            }
        ]
    }
    client = MagicMock()
    client.chat.completions.create = MagicMock(
        return_value=_fake_openai_completion_json(batch_json)
    )
    settings = {"openai_api_key": "sk-test-key", "model": "gpt-test"}
    out = compile_resolution_rules_batch_openai(
        [("evt-1", "event", "resolve 2 hours after first pitch")],
        settings,
        client=client,
    )
    assert "evt-1" in out
    assert out["evt-1"].kind == "offset_from_anchor"
    assert out["evt-1"].anchor == "event_datetime"
    assert out["evt-1"].offset_hours == 2
    client.chat.completions.create.assert_called_once()


def test_maybe_compile_resolution_for_template_data_with_mock_client() -> None:
    """Upload path merges AI JSON into resolution_date_spec when rule is set."""
    client = MagicMock()
    client.chat.completions.create = MagicMock(
        return_value=_fake_openai_completion_json(
            {
                "items": [
                    {
                        "template_id": "music-yn-01",
                        "spec": {
                            "kind": "offset_from_anchor",
                            "anchor": "release_date",
                            "offset_days": 7,
                            "offset_hours": 0,
                        },
                    }
                ]
            }
        )
    )
    data = {
        "id": "music-yn-01",
        "question_family": "content",
        "resolution_date_rule": "Resolution date should be 7 days after the album release date.",
    }
    settings = {"openai_api_key": "sk-test", "model": "gpt-test"}
    merged = maybe_compile_resolution_for_template_data(data, settings, client=client)
    assert merged["resolution_date_spec"] == {
        "kind": "offset_from_anchor",
        "anchor": "release_date",
        "metadata_key": None,
        "offset_days": 7,
        "offset_hours": 0,
        "calendar_year": None,
        "calendar_month": None,
        "calendar_day": None,
        "year_policy": None,
        "end_offset_days": None,
        "local_hour": None,
        "local_minute": None,
        "iana_timezone": None,
    }
    assert merged["resolution_date_rule"] == data["resolution_date_rule"]
    client.chat.completions.create.assert_called_once()


def test_maybe_compile_infer_start_date_plus_days_skips_openai() -> None:
    client = MagicMock()
    data = {
        "id": "movie-yn-01",
        "question_family": "content",
        "resolution_date_rule": "Resolution date should be start_date + 4 days.",
    }
    merged = maybe_compile_resolution_for_template_data(
        data, {"openai_api_key": "sk-test"}, client=client
    )
    spec = merged["resolution_date_spec"]
    assert spec["kind"] == "offset_from_anchor"
    assert spec["anchor"] == "question_start"
    assert spec["offset_days"] == 4
    client.chat.completions.create.assert_not_called()


def test_maybe_compile_infer_overrides_wrong_bundled_spec() -> None:
    """Re-uploaded JSON may carry an old AI spec; phrase match should win."""
    client = MagicMock()
    data = {
        "id": "movie-yn-01",
        "question_family": "content",
        "resolution_date_rule": "Resolution date should be start_date + 4 days.",
        "resolution_date_spec": {
            "kind": "offset_from_anchor",
            "anchor": "release_date",
            "offset_days": 4,
        },
    }
    merged = maybe_compile_resolution_for_template_data(
        data, {"openai_api_key": "sk-test"}, client=client
    )
    assert merged["resolution_date_spec"]["anchor"] == "question_start"
    client.chat.completions.create.assert_not_called()


def test_maybe_compile_infer_release_date_plus_days() -> None:
    client = MagicMock()
    data = {
        "id": "t-rel",
        "question_family": "content",
        "resolution_date_rule": "Use release_date + 10 days for settlement.",
    }
    merged = maybe_compile_resolution_for_template_data(
        data, {"openai_api_key": "sk-test"}, client=client
    )
    assert merged["resolution_date_spec"]["anchor"] == "release_date"
    assert merged["resolution_date_spec"]["offset_days"] == 10
    client.chat.completions.create.assert_not_called()


def test_maybe_compile_skips_openai_when_spec_already_present() -> None:
    client = MagicMock()
    data = {
        "id": "t1",
        "question_family": "content",
        "resolution_date_rule": "ignored when spec exists",
        "resolution_date_spec": {
            "kind": "none",
        },
    }
    out = maybe_compile_resolution_for_template_data(
        data, {"openai_api_key": "sk-x"}, client=client
    )
    assert out["resolution_date_spec"]["kind"] == "none"
    client.chat.completions.create.assert_not_called()


def test_absolute_calendar_date_event() -> None:
    spec = ResolutionDateSpec(
        kind="absolute_calendar_date",
        calendar_year=2026,
        calendar_month=10,
        calendar_day=20,
    )
    base = datetime(2026, 5, 15, 19, 0, 0)
    ctx = EventResolutionContext(
        event_datetime=base,
        question_start=base + timedelta(hours=-24),
        question_expiration=base,
        metadata={},
    )
    out = compute_resolution_datetime_for_event(spec, ctx)
    assert out == datetime(2026, 10, 20, 0, 0, 0)


def test_infer_event_date_minus_hours_snake_case() -> None:
    data = {
        "id": "evt-t",
        "question_family": "event",
        "start_date_rule": "event_date_minus_48_hours",
    }
    merged = maybe_compile_resolution_for_template_data(data, {"openai_api_key": "sk-unused"})
    spec = merged["start_date_spec"]
    assert spec["kind"] == "offset_from_anchor"
    assert spec["anchor"] == "event_datetime"
    assert spec["offset_hours"] == -48


def test_maybe_compile_stock_strips_start_and_expiration_fields() -> None:
    data = {
        "id": "st1",
        "question_family": "stock",
        "resolution_date_rule": "ignored",
        "start_date_rule": "ignored",
        "expiration_date_rule": "ignored",
    }
    out = maybe_compile_resolution_for_template_data(data, {"openai_api_key": "sk-x"})
    assert "resolution_date_rule" not in out
    assert "start_date_rule" not in out


def test_local_time_on_anchor_eastern_maps_to_naive_utc() -> None:
    spec = ResolutionDateSpec(
        kind="local_time_on_anchor_date",
        anchor="event_datetime",
        local_hour=11,
        local_minute=0,
        iana_timezone="America/New_York",
    )
    # 2026-05-15 21:40 UTC = 17:40 Eastern; same calendar day in US Eastern.
    base = datetime(2026, 5, 15, 21, 40, 0)
    ctx = EventResolutionContext(
        event_datetime=base,
        question_start=base + timedelta(hours=-24),
        question_expiration=base,
        metadata={},
    )
    out = compute_resolution_datetime_for_event(spec, ctx)
    assert out is not None
    assert out.hour == 15  # 11:00 Eastern → 15:00 UTC on this date (EDT)


def test_compile_mls_resolution_24_hours_after_expiration_rule_openai() -> None:
    client = MagicMock()
    payload = {
        "items": [
            {
                "template_id": "MLS-006",
                "field": "resolution",
                "spec": {
                    "kind": "offset_from_anchor",
                    "anchor": "question_expiration",
                    "offset_days": 0,
                    "offset_hours": 24,
                },
            }
        ]
    }
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(payload), refusal=None))]
    )
    data = {
        "id": "MLS-006",
        "question_family": "event",
        "resolution_date_rule": "24 hours after expiration_date_rule",
    }
    merged = maybe_compile_resolution_for_template_data(
        data, {"openai_api_key": "sk-test", "model": "gpt-test"}, client=client
    )
    assert merged["resolution_date_spec"]["anchor"] == "question_expiration"
    assert merged["resolution_date_spec"]["offset_hours"] == 24


def test_local_time_day_after_event_resolves_after_expiration() -> None:
    spec = ResolutionDateSpec(
        kind="local_time_on_anchor_date",
        anchor="event_datetime",
        offset_days=1,
        local_hour=0,
        local_minute=1,
        iana_timezone="America/New_York",
    )
    event = datetime(2026, 7, 17, 0, 30, 0)
    expiration = datetime(2026, 7, 16, 14, 0, 0)
    ctx = EventResolutionContext(
        event_datetime=event,
        question_start=event + timedelta(hours=-48),
        question_expiration=expiration,
        metadata={},
    )
    out = compute_resolution_datetime_for_event(spec, ctx)
    assert out == datetime(2026, 7, 17, 4, 1, 0)
    assert out > expiration


@pytest.mark.live_openai
def test_live_openai_compiles_natural_language_resolution_rules() -> None:
    """Call the real Chat Completions API (opt-in: RUN_LIVE_OPENAI_TESTS=1 + OPENAI_API_KEY).

    Run with ``pytest -m live_openai -s`` to print the returned specs. Uses
    ``OPENAI_RESOLUTION_COMPILE_MODEL`` if set, otherwise ``gpt-4o-mini``.
    """

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    assert api_key, "OPENAI_API_KEY must be set for live_openai tests"

    model = os.environ.get("OPENAI_RESOLUTION_COMPILE_MODEL", "gpt-4o-mini")
    settings: dict = {
        "openai_api_key": api_key,
        "model": model,
    }
    entries = [
        (
            "tpl-content-live",
            "content",
            "Resolution date should be 7 days after the album release date.",
        ),
        (
            "tpl-event-live",
            "event",
            "Resolve two hours after scheduled game start (kickoff).",
        ),
    ]
    out = compile_resolution_rules_batch_openai(entries, settings)

    assert set(out.keys()) == {"tpl-content-live", "tpl-event-live"}
    content_spec = out["tpl-content-live"]
    event_spec = out["tpl-event-live"]

    print(
        "\n--- live OpenAI resolution compile (content) ---\n",
        json.dumps(content_spec.model_dump(mode="json"), indent=2),
    )
    print(
        "\n--- live OpenAI resolution compile (event) ---\n",
        json.dumps(event_spec.model_dump(mode="json"), indent=2),
    )

    assert content_spec.kind != "none"
    assert event_spec.kind != "none"

    if content_spec.kind == "offset_from_anchor" and content_spec.anchor == "release_date":
        assert 5 <= (content_spec.offset_days or 0) <= 10, content_spec.model_dump()
    elif content_spec.kind == "window_end":
        assert content_spec.end_offset_days is not None
    else:
        assert content_spec.kind in (
            "offset_from_anchor",
            "calendar_in_year",
            "metadata_date",
        ), content_spec.model_dump()

    if event_spec.kind == "offset_from_anchor" and event_spec.anchor == "event_datetime":
        assert 1 <= (event_spec.offset_hours or 0) <= 4, event_spec.model_dump()
    elif event_spec.kind == "offset_from_anchor":
        assert event_spec.anchor in (
            "event_datetime",
            "question_start",
            "question_expiration",
        ), event_spec.model_dump()
