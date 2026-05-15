"""Pipeline helpers (Epic 8)."""

from __future__ import annotations

import pytest

from core.pipeline import filter_templates_for_subcategory, is_template_enabled, run_pipeline
from core.parsers.contracts import NormalizedBundle, NormalizedEvent
from core.template_config.schema import QuestionTemplate


def _tpl(tid: str, sub: str = "MLB") -> QuestionTemplate:
    return QuestionTemplate(
        id=tid,
        subcategory=sub,
        question_family="event",
        question="Q",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
    )


def test_filter_templates_respects_subcategory_and_enabled():
    templates = {
        "a": _tpl("mlb_a", "MLB"),
        "b": _tpl("mlb_b", "MLB"),
        "c": _tpl("mkt", "Markets"),
    }
    settings = {"templates_enabled": {"mlb_a": True, "mlb_b": False}}
    out = filter_templates_for_subcategory(templates, "MLB", settings)
    assert [t.id for t in out] == ["mlb_a"]


def test_filter_templates_normalizes_subcategory_text():
    templates = {
        "a": _tpl("mlb_a", "MLB"),
        "b": _tpl("ent", "Entertainment"),
    }
    out = filter_templates_for_subcategory(templates, "mlb", {"templates_enabled": {}})
    assert [t.id for t in out] == ["mlb_a"]


def test_is_template_enabled_defaults():
    assert is_template_enabled("x", {}) is True
    assert is_template_enabled("x", {"templates_enabled": None}) is True


def test_format_generation_failure_quota_message():
    from core.generation.batch_executor import BatchResult, FailedBatch
    from core.pipeline import _format_generation_failure_message

    br = BatchResult(
        failed_batches=[
            FailedBatch(
                batch_index=0,
                item_count=5,
                error="Error code: 429 - {'error': {'code': 'insufficient_quota'}}",
            )
        ]
    )
    msg = _format_generation_failure_message(br)
    assert "billing" in msg.lower() or "quota" in msg.lower()
    assert "OpenAI" in msg


def test_max_generated_questions_helper():
    from core.pipeline import _max_generated_questions

    assert _max_generated_questions({}) is None
    assert _max_generated_questions({"max_generated_questions": None}) is None
    assert _max_generated_questions({"max_generated_questions": ""}) is None
    assert _max_generated_questions({"max_generated_questions": 0}) is None
    assert _max_generated_questions({"max_generated_questions": 5}) == 5


def test_successful_prompt_items_skips_failed_batch():
    from core.generation import PromptItem
    from core.generation.batch_executor import BatchResult, FailedBatch
    from core.parsers.contracts import NormalizedEvent
    from core.pipeline import _successful_prompt_items

    ev = NormalizedEvent(
        event_id="1",
        home_team="A",
        away_team="B",
        event_datetime="2026-05-15T21:40:00",
        subcategory="MLB",
    )
    t = _tpl("t1")
    items = [PromptItem(template=t, event=ev, players=[])] * 5
    br = BatchResult(failed_batches=[FailedBatch(batch_index=0, item_count=5, error="x")])
    assert _successful_prompt_items(items, br, batch_size=5) == []


def test_run_pipeline_returns_structured_template_error(monkeypatch):
    monkeypatch.setattr(
        "core.pipeline.load_normalized_bundle",
        lambda *_a, **_k: NormalizedBundle(events=[_event()]),
    )
    monkeypatch.setattr(
        "core.pipeline.load_template_dir",
        lambda _p: (_ for _ in ()).throw(ValueError("bad template")),
    )

    result = run_pipeline(_settings())

    assert result.success is False
    assert result.message == "Template configuration error: bad template"


def test_run_pipeline_returns_structured_bad_batch_size(monkeypatch):
    monkeypatch.setattr(
        "core.pipeline.load_normalized_bundle",
        lambda *_a, **_k: NormalizedBundle(events=[_event()]),
    )
    monkeypatch.setattr(
        "core.pipeline.load_template_dir",
        lambda _p: {"tpl": _tpl("tpl")},
    )

    result = run_pipeline(_settings(batch_size="not-an-int"))

    assert result.success is False
    assert "Invalid batch_size" in (result.message or "")


def test_run_pipeline_missing_topic_import_id_raises_before_generation(monkeypatch):
    monkeypatch.setattr(
        "core.pipeline.load_normalized_bundle",
        lambda *_a, **_k: NormalizedBundle(events=[_event()]),
    )
    monkeypatch.setattr(
        "core.pipeline.load_template_dir",
        lambda _p: {"tpl": _tpl("tpl")},
    )

    def _unexpected_executor(*_args, **_kwargs):
        raise AssertionError("generation should not start without topic_import_id")

    monkeypatch.setattr("core.pipeline.BatchExecutor", _unexpected_executor)

    with pytest.raises(ValueError, match="topic_import_id is required in config but was not set"):
        run_pipeline(_settings(openai_api_key="sk-test", topic_import_id=""))


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="EV1",
        home_team="Home",
        away_team="Away",
        event_datetime="2026-05-15T12:00:00",
        subcategory="MLB",
    )


def _settings(**overrides):
    settings = {
        "openai_api_key": "sk-test",
        "topic_import_id": "mlb-regular-season",
        "templates_directory": "templates",
        "templates_enabled": {},
        "inputs": {"category_key": "mlb"},
    }
    settings.update(overrides)
    return settings
