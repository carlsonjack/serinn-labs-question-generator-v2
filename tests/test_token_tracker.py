"""Tests for token usage tracking and cost estimation (EPIC 5, Task 5.4)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.generation.token_tracker import (
    RunCostSummary,
    TokenUsage,
    _DEFAULT_PRICING,
    _FALLBACK_PRICING,
    _resolve_pricing,
    build_cost_summary,
    estimate_cost,
    extract_token_usage,
    log_cost_summary,
)


# ---------------------------------------------------------------------------
# TokenUsage dataclass
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_defaults_are_zero(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_explicit_values(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.prompt_tokens == 100
        assert u.completion_tokens == 50
        assert u.total_tokens == 150


# ---------------------------------------------------------------------------
# RunCostSummary dataclass
# ---------------------------------------------------------------------------


class TestRunCostSummary:
    def test_defaults(self):
        s = RunCostSummary()
        assert s.prompt_tokens == 0
        assert s.completion_tokens == 0
        assert s.total_tokens == 0
        assert s.estimated_cost_usd == 0.0
        assert s.model == ""
        assert s.batch_count == 0

    def test_batch_count_from_usages(self):
        s = RunCostSummary(batch_usages=[TokenUsage(), TokenUsage(), TokenUsage()])
        assert s.batch_count == 3

    def test_stores_model(self):
        s = RunCostSummary(model="gpt-5.4")
        assert s.model == "gpt-5.4"


# ---------------------------------------------------------------------------
# extract_token_usage
# ---------------------------------------------------------------------------


class TestExtractTokenUsage:
    def test_extracts_from_real_shaped_response(self):
        response = MagicMock()
        response.usage.prompt_tokens = 500
        response.usage.completion_tokens = 200
        response.usage.total_tokens = 700

        usage = extract_token_usage(response)

        assert usage.prompt_tokens == 500
        assert usage.completion_tokens == 200
        assert usage.total_tokens == 700

    def test_none_usage_returns_zeros(self):
        response = MagicMock()
        response.usage = None

        usage = extract_token_usage(response)

        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_missing_usage_attr_returns_zeros(self):
        response = object()

        usage = extract_token_usage(response)

        assert usage.total_tokens == 0

    def test_partial_usage_fields(self):
        usage_obj = MagicMock(spec=[])
        usage_obj.prompt_tokens = 300
        response = MagicMock()
        response.usage = usage_obj

        usage = extract_token_usage(response)

        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_none_field_values_coerced_to_zero(self):
        response = MagicMock()
        response.usage.prompt_tokens = None
        response.usage.completion_tokens = 100
        response.usage.total_tokens = None

        usage = extract_token_usage(response)

        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 100
        assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Pricing resolution
# ---------------------------------------------------------------------------


class TestResolvePricing:
    def test_known_model_returns_builtin(self):
        pricing = _resolve_pricing("gpt-4o", {})
        assert pricing == _DEFAULT_PRICING["gpt-4o"]

    def test_unknown_model_returns_fallback(self):
        pricing = _resolve_pricing("some-future-model", {})
        assert pricing == _FALLBACK_PRICING

    def test_settings_override_takes_precedence(self):
        settings: dict[str, Any] = {
            "model_pricing": {
                "gpt-4o": {"input": 1.00, "output": 5.00},
            }
        }
        pricing = _resolve_pricing("gpt-4o", settings)
        assert pricing["input"] == 1.00
        assert pricing["output"] == 5.00

    def test_settings_override_for_unknown_model(self):
        settings: dict[str, Any] = {
            "model_pricing": {
                "custom-model": {"input": 0.50, "output": 2.00},
            }
        }
        pricing = _resolve_pricing("custom-model", settings)
        assert pricing["input"] == 0.50
        assert pricing["output"] == 2.00

    def test_empty_model_pricing_in_settings(self):
        pricing = _resolve_pricing("gpt-4o", {"model_pricing": {}})
        assert pricing == _DEFAULT_PRICING["gpt-4o"]

    def test_none_model_pricing_in_settings(self):
        pricing = _resolve_pricing("gpt-4o", {"model_pricing": None})
        assert pricing == _DEFAULT_PRICING["gpt-4o"]


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_zero_tokens_zero_cost(self):
        assert estimate_cost(0, 0, "gpt-4o") == 0.0

    def test_known_model_cost(self):
        cost = estimate_cost(1_000_000, 1_000_000, "gpt-4o")
        assert cost == 2.50 + 10.00

    def test_proportional_to_tokens(self):
        cost = estimate_cost(500_000, 250_000, "gpt-4o")
        expected = (500_000 / 1_000_000) * 2.50 + (250_000 / 1_000_000) * 10.00
        assert cost == round(expected, 6)

    def test_unknown_model_uses_fallback(self):
        cost = estimate_cost(1_000_000, 1_000_000, "unknown-model")
        expected = _FALLBACK_PRICING["input"] + _FALLBACK_PRICING["output"]
        assert cost == expected

    def test_settings_pricing_override(self):
        settings: dict[str, Any] = {
            "model_pricing": {"gpt-4o": {"input": 1.00, "output": 2.00}}
        }
        cost = estimate_cost(1_000_000, 1_000_000, "gpt-4o", settings)
        assert cost == 3.00

    def test_none_settings_uses_defaults(self):
        cost = estimate_cost(1_000_000, 0, "gpt-4o", None)
        assert cost == 2.50

    def test_small_token_count_precision(self):
        cost = estimate_cost(150, 50, "gpt-4o")
        expected = (150 / 1_000_000) * 2.50 + (50 / 1_000_000) * 10.00
        assert cost == round(expected, 6)


# ---------------------------------------------------------------------------
# build_cost_summary
# ---------------------------------------------------------------------------


class TestBuildCostSummary:
    def test_empty_usages(self):
        summary = build_cost_summary([], "gpt-4o")
        assert summary.prompt_tokens == 0
        assert summary.completion_tokens == 0
        assert summary.total_tokens == 0
        assert summary.estimated_cost_usd == 0.0
        assert summary.model == "gpt-4o"
        assert summary.batch_count == 0

    def test_single_batch(self):
        u = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        summary = build_cost_summary([u], "gpt-4o")
        assert summary.prompt_tokens == 1000
        assert summary.completion_tokens == 500
        assert summary.total_tokens == 1500
        assert summary.batch_count == 1
        assert summary.estimated_cost_usd > 0

    def test_multiple_batches_aggregate(self):
        u1 = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        u2 = TokenUsage(prompt_tokens=2000, completion_tokens=800, total_tokens=2800)
        summary = build_cost_summary([u1, u2], "gpt-4o")
        assert summary.prompt_tokens == 3000
        assert summary.completion_tokens == 1300
        assert summary.total_tokens == 4300
        assert summary.batch_count == 2

    def test_cost_matches_estimate_cost(self):
        u = TokenUsage(prompt_tokens=10000, completion_tokens=5000, total_tokens=15000)
        summary = build_cost_summary([u], "gpt-4o")
        expected = estimate_cost(10000, 5000, "gpt-4o")
        assert summary.estimated_cost_usd == expected

    def test_settings_passed_to_pricing(self):
        settings: dict[str, Any] = {
            "model_pricing": {"gpt-4o": {"input": 100.0, "output": 100.0}}
        }
        u = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
        summary = build_cost_summary([u], "gpt-4o", settings)
        assert summary.estimated_cost_usd == 200.0

    def test_preserves_individual_usages(self):
        u1 = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        u2 = TokenUsage(prompt_tokens=200, completion_tokens=75, total_tokens=275)
        summary = build_cost_summary([u1, u2], "gpt-4o")
        assert len(summary.batch_usages) == 2
        assert summary.batch_usages[0] is u1
        assert summary.batch_usages[1] is u2


# ---------------------------------------------------------------------------
# log_cost_summary
# ---------------------------------------------------------------------------


class TestLogCostSummary:
    def test_logs_without_error(self, caplog):
        summary = RunCostSummary(
            prompt_tokens=5000,
            completion_tokens=2000,
            total_tokens=7000,
            estimated_cost_usd=0.0325,
            model="gpt-4o",
            batch_usages=[TokenUsage(prompt_tokens=5000, completion_tokens=2000, total_tokens=7000)],
        )
        with caplog.at_level(logging.INFO, logger="core.generation.token_tracker"):
            log_cost_summary(summary)

        assert len(caplog.records) == 2

    def test_token_counts_in_log(self, caplog):
        summary = RunCostSummary(
            prompt_tokens=12345,
            completion_tokens=6789,
            total_tokens=19134,
            estimated_cost_usd=0.05,
            model="gpt-4o",
            batch_usages=[TokenUsage()],
        )
        with caplog.at_level(logging.INFO, logger="core.generation.token_tracker"):
            log_cost_summary(summary)

        usage_line = caplog.records[0].message
        assert "12,345" in usage_line
        assert "6,789" in usage_line
        assert "19,134" in usage_line

    def test_cost_and_model_in_log(self, caplog):
        summary = RunCostSummary(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            estimated_cost_usd=0.0075,
            model="gpt-5.4",
            batch_usages=[TokenUsage()],
        )
        with caplog.at_level(logging.INFO, logger="core.generation.token_tracker"):
            log_cost_summary(summary)

        cost_line = caplog.records[1].message
        assert "$0.0075" in cost_line
        assert "gpt-5.4" in cost_line
        assert "1 batch" in cost_line

    def test_zero_cost_logs_cleanly(self, caplog):
        summary = RunCostSummary()
        with caplog.at_level(logging.INFO, logger="core.generation.token_tracker"):
            log_cost_summary(summary)

        assert len(caplog.records) == 2


# ---------------------------------------------------------------------------
# Integration: BatchExecutor captures token usage
# ---------------------------------------------------------------------------


class TestBatchExecutorTokenIntegration:
    """Verify that BatchExecutor wires token tracking end-to-end."""

    def _settings(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "openai_api_key": "sk-test-key",
            "model": "gpt-4o",
            "batch_size": 100,
        }
        base.update(overrides)
        return base

    def _make_response(
        self,
        questions: list | None = None,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> MagicMock:
        from core.generation.prompt_builder import GeneratedQuestion, GeneratedQuestionBatch

        if questions is None:
            questions = [
                GeneratedQuestion(
                    template_id="mlb_game_winner",
                    event_id="MLB000000",
                    question="Who will win?",
                    answer_options="A||B",
                )
            ]
        batch = GeneratedQuestionBatch(questions=questions)
        message = MagicMock()
        message.parsed = batch
        message.refusal = None
        choice = MagicMock()
        choice.message = message
        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        usage.total_tokens = prompt_tokens + completion_tokens
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    def _make_items(self, n: int = 1):
        from core.generation.prompt_builder import PromptItem
        from core.parsers.contracts import NormalizedEvent
        from core.template_config.schema import QuestionTemplate

        template = QuestionTemplate(
            id="mlb_game_winner",
            subcategory="MLB",
            question_family="event",
            question="Who will win {home_team} vs {away_team}?",
            answer_type="multiple_choice",
            answer_options="{home_team}||{away_team}",
            priority=1,
            requires_entities=False,
        )
        return [
            PromptItem(
                template=template,
                event=NormalizedEvent(
                    event_id=f"MLB{i:06d}",
                    home_team="Athletics",
                    away_team="Giants",
                    event_datetime="2026-05-15T21:40:00",
                    subcategory="MLB",
                ),
            )
            for i in range(n)
        ]

    def test_result_has_token_usages(self):
        from core.generation.batch_executor import BatchExecutor

        client = MagicMock()
        client.beta.chat.completions.parse.return_value = self._make_response(
            prompt_tokens=500, completion_tokens=200
        )
        executor = BatchExecutor(self._settings(), client=client)

        result = executor.execute(self._make_items(1))

        assert len(result.token_usages) == 1
        assert result.token_usages[0].prompt_tokens == 500
        assert result.token_usages[0].completion_tokens == 200

    def test_result_has_cost_summary(self):
        from core.generation.batch_executor import BatchExecutor

        client = MagicMock()
        client.beta.chat.completions.parse.return_value = self._make_response()
        executor = BatchExecutor(self._settings(), client=client)

        result = executor.execute(self._make_items(1))

        assert result.cost_summary is not None
        assert result.cost_summary.model == "gpt-4o"
        assert result.cost_summary.estimated_cost_usd >= 0

    def test_multi_batch_aggregates_usage(self):
        from core.generation.batch_executor import BatchExecutor

        client = MagicMock()
        client.beta.chat.completions.parse.side_effect = [
            self._make_response(prompt_tokens=300, completion_tokens=100),
            self._make_response(prompt_tokens=200, completion_tokens=80),
        ]
        executor = BatchExecutor(self._settings(batch_size=1), client=client)

        result = executor.execute(self._make_items(2))

        assert len(result.token_usages) == 2
        assert result.cost_summary is not None
        assert result.cost_summary.prompt_tokens == 500
        assert result.cost_summary.completion_tokens == 180
        assert result.cost_summary.batch_count == 2

    def test_failed_batch_does_not_add_usage(self):
        from core.generation.batch_executor import BatchExecutor

        client = MagicMock()
        client.beta.chat.completions.parse.side_effect = [
            RuntimeError("API error"),
            self._make_response(prompt_tokens=400, completion_tokens=150),
        ]
        executor = BatchExecutor(self._settings(batch_size=1), client=client)

        result = executor.execute(self._make_items(2))

        assert len(result.token_usages) == 1
        assert result.token_usages[0].prompt_tokens == 400
        assert result.cost_summary.prompt_tokens == 400

    def test_empty_input_has_zero_cost(self):
        from core.generation.batch_executor import BatchExecutor

        executor = BatchExecutor(self._settings(), client=MagicMock())
        result = executor.execute([])

        assert result.cost_summary is None
        assert len(result.token_usages) == 0
