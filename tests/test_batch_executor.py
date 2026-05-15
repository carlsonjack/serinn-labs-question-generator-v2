"""Tests for the batch executor (EPIC 5, Task 5.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.generation.batch_executor import (
    DEFAULT_BATCH_SIZE,
    BatchExecutor,
    BatchResult,
    FailedBatch,
)
from core.generation.prompt_builder import (
    GeneratedQuestion,
    GeneratedQuestionBatch,
    PromptBuilder,
    PromptItem,
)
from core.parsers.contracts import NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _settings(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "openai_api_key": "sk-test-key",
        "model": "gpt-4o",
        "batch_size": 100,
    }
    base.update(overrides)
    return base


def _event(
    event_id: str = "MLB000657",
    home_team: str = "Athletics",
    away_team: str = "Giants",
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        event_datetime="2026-05-15T21:40:00",
        subcategory="MLB",
    )


def _game_winner_template() -> QuestionTemplate:
    return QuestionTemplate(
        id="mlb_game_winner",
        subcategory="MLB",
        question_family="event",
        question="Who will win {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{home_team}||{away_team}",
        priority=1,
        requires_entities=False,
    )


def _make_items(n: int) -> list[PromptItem]:
    """Create *n* distinct prompt items."""
    return [
        PromptItem(
            template=_game_winner_template(),
            event=_event(event_id=f"MLB{i:06d}"),
        )
        for i in range(n)
    ]


def _mock_generated_question(event_id: str = "MLB000657") -> GeneratedQuestion:
    return GeneratedQuestion(
        template_id="mlb_game_winner",
        event_id=event_id,
        question="Who will win: Athletics or Giants?",
        answer_options="Athletics||Giants",
    )


def _mock_openai_response(questions: list[GeneratedQuestion]) -> MagicMock:
    """Build a fake OpenAI ParsedChatCompletion response."""
    batch = GeneratedQuestionBatch(questions=questions)
    message = MagicMock()
    message.parsed = batch
    message.refusal = None
    choice = MagicMock()
    choice.message = message
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _failing_openai_client(error: Exception) -> MagicMock:
    """Return an OpenAI client mock whose parse() always raises *error*."""
    client = MagicMock()
    client.beta.chat.completions.parse.side_effect = error
    return client


def _succeeding_openai_client(
    questions_per_call: list[list[GeneratedQuestion]],
) -> MagicMock:
    """Return an OpenAI client mock that yields given questions on successive calls."""
    client = MagicMock()
    client.beta.chat.completions.parse.side_effect = [
        _mock_openai_response(qs) for qs in questions_per_call
    ]
    return client


# ---------------------------------------------------------------------------
# BatchResult dataclass
# ---------------------------------------------------------------------------


class TestBatchResult:
    def test_empty_result_defaults(self):
        r = BatchResult()
        assert r.total_questions == 0
        assert r.all_succeeded is True
        assert r.total_batches == 0
        assert r.successful_batches == 0

    def test_all_succeeded_true_when_no_failures(self):
        r = BatchResult(
            questions=[_mock_generated_question()],
            total_batches=1,
            successful_batches=1,
        )
        assert r.all_succeeded is True

    def test_all_succeeded_false_with_failure(self):
        r = BatchResult(
            failed_batches=[FailedBatch(batch_index=0, item_count=5, error="boom")],
            total_batches=1,
            successful_batches=0,
        )
        assert r.all_succeeded is False

    def test_total_questions_counts_list(self):
        r = BatchResult(questions=[_mock_generated_question()] * 7)
        assert r.total_questions == 7


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunking:
    def test_default_batch_size_from_settings(self):
        executor = BatchExecutor(_settings(), client=MagicMock())
        assert executor.batch_size == 100

    def test_custom_batch_size(self):
        executor = BatchExecutor(_settings(batch_size=25), client=MagicMock())
        assert executor.batch_size == 25

    def test_chunk_evenly_divisible(self):
        executor = BatchExecutor(_settings(batch_size=3), client=MagicMock())
        chunks = executor._chunk(_make_items(9))
        assert len(chunks) == 3
        assert all(len(c) == 3 for c in chunks)

    def test_chunk_remainder(self):
        executor = BatchExecutor(_settings(batch_size=4), client=MagicMock())
        chunks = executor._chunk(_make_items(10))
        assert len(chunks) == 3
        assert [len(c) for c in chunks] == [4, 4, 2]

    def test_chunk_single_item(self):
        executor = BatchExecutor(_settings(batch_size=100), client=MagicMock())
        chunks = executor._chunk(_make_items(1))
        assert len(chunks) == 1
        assert len(chunks[0]) == 1

    def test_chunk_empty(self):
        executor = BatchExecutor(_settings(), client=MagicMock())
        chunks = executor._chunk([])
        assert chunks == []

    def test_batch_size_string_coerced_to_int(self):
        executor = BatchExecutor(_settings(batch_size="50"), client=MagicMock())
        assert executor.batch_size == 50

    def test_items_larger_than_batch_produces_multiple_chunks(self):
        executor = BatchExecutor(_settings(batch_size=2), client=MagicMock())
        chunks = executor._chunk(_make_items(5))
        assert len(chunks) == 3


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_raises_when_no_api_key(self):
        executor = BatchExecutor(_settings(openai_api_key=""))
        with pytest.raises(ValueError, match="openai_api_key"):
            _ = executor.client

    def test_injected_client_used_directly(self):
        mock_client = MagicMock()
        executor = BatchExecutor(_settings(), client=mock_client)
        assert executor.client is mock_client

    def test_model_from_settings(self):
        executor = BatchExecutor(_settings(model="gpt-5.4"), client=MagicMock())
        assert executor.model == "gpt-5.4"

    def test_model_default_fallback(self):
        s = _settings()
        del s["model"]
        executor = BatchExecutor(s, client=MagicMock())
        assert executor.model == "gpt-4o"


# ---------------------------------------------------------------------------
# execute() — happy path
# ---------------------------------------------------------------------------


class TestExecuteHappyPath:
    def test_empty_items_returns_empty_result(self):
        executor = BatchExecutor(_settings(), client=MagicMock())
        result = executor.execute([])
        assert result.total_batches == 0
        assert result.total_questions == 0
        assert result.all_succeeded is True

    def test_single_batch_returns_questions(self):
        q = _mock_generated_question()
        client = _succeeding_openai_client([[q]])
        executor = BatchExecutor(_settings(batch_size=100), client=client)

        result = executor.execute(_make_items(1))

        assert result.total_batches == 1
        assert result.successful_batches == 1
        assert result.total_questions == 1
        assert result.questions[0].event_id == q.event_id

    def test_multiple_batches_aggregated(self):
        q1 = _mock_generated_question("MLB000000")
        q2 = _mock_generated_question("MLB000001")
        q3 = _mock_generated_question("MLB000002")
        client = _succeeding_openai_client([[q1, q2], [q3]])
        executor = BatchExecutor(_settings(batch_size=2), client=client)

        result = executor.execute(_make_items(3))

        assert result.total_batches == 2
        assert result.successful_batches == 2
        assert result.total_questions == 3

    def test_api_called_with_correct_model(self):
        client = _succeeding_openai_client([[_mock_generated_question()]])
        executor = BatchExecutor(_settings(model="gpt-5.4"), client=client)

        executor.execute(_make_items(1))

        call_kwargs = client.beta.chat.completions.parse.call_args
        assert call_kwargs.kwargs["model"] == "gpt-5.4"

    def test_api_called_with_response_format(self):
        client = _succeeding_openai_client([[_mock_generated_question()]])
        executor = BatchExecutor(_settings(), client=client)

        executor.execute(_make_items(1))

        call_kwargs = client.beta.chat.completions.parse.call_args
        assert call_kwargs.kwargs["response_format"] is GeneratedQuestionBatch

    def test_api_receives_prompt_builder_messages(self):
        client = _succeeding_openai_client([[_mock_generated_question()]])
        executor = BatchExecutor(_settings(), client=client)

        executor.execute(_make_items(1))

        call_kwargs = client.beta.chat.completions.parse.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"


# ---------------------------------------------------------------------------
# execute() — error handling
# ---------------------------------------------------------------------------


class TestExecuteErrorHandling:
    def test_failed_batch_recorded_and_continues(self):
        q = _mock_generated_question("MLB000002")
        client = MagicMock()
        client.beta.chat.completions.parse.side_effect = [
            RuntimeError("API timeout"),
            _mock_openai_response([q]),
        ]
        executor = BatchExecutor(_settings(batch_size=2), client=client)

        result = executor.execute(_make_items(4))

        assert result.total_batches == 2
        assert result.successful_batches == 1
        assert len(result.failed_batches) == 1
        assert result.failed_batches[0].batch_index == 0
        assert "API timeout" in result.failed_batches[0].error
        assert result.total_questions == 1

    def test_all_batches_fail(self):
        client = _failing_openai_client(ConnectionError("network down"))
        executor = BatchExecutor(_settings(batch_size=2), client=client)

        result = executor.execute(_make_items(4))

        assert result.total_batches == 2
        assert result.successful_batches == 0
        assert len(result.failed_batches) == 2
        assert result.total_questions == 0
        assert not result.all_succeeded

    def test_failed_batch_preserves_item_count(self):
        client = _failing_openai_client(ValueError("bad request"))
        executor = BatchExecutor(_settings(batch_size=3), client=client)

        result = executor.execute(_make_items(5))

        assert result.failed_batches[0].item_count == 3
        assert result.failed_batches[1].item_count == 2

    def test_refusal_raises_runtime_error(self):
        message = MagicMock()
        message.parsed = None
        message.refusal = "I cannot do that"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]

        client = MagicMock()
        client.beta.chat.completions.parse.return_value = response
        executor = BatchExecutor(_settings(), client=client)

        result = executor.execute(_make_items(1))

        assert len(result.failed_batches) == 1
        assert "refusal" in result.failed_batches[0].error

    def test_null_parsed_no_refusal(self):
        message = MagicMock()
        message.parsed = None
        message.refusal = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]

        client = MagicMock()
        client.beta.chat.completions.parse.return_value = response
        executor = BatchExecutor(_settings(), client=client)

        result = executor.execute(_make_items(1))

        assert len(result.failed_batches) == 1
        assert "no parsed output" in result.failed_batches[0].error


# ---------------------------------------------------------------------------
# Custom PromptBuilder injection
# ---------------------------------------------------------------------------


class TestPromptBuilderInjection:
    def test_uses_default_builder_when_none_given(self):
        executor = BatchExecutor(_settings(), client=MagicMock())
        assert isinstance(executor.prompt_builder, PromptBuilder)

    def test_uses_injected_builder(self):
        builder = PromptBuilder()
        executor = BatchExecutor(_settings(), prompt_builder=builder, client=MagicMock())
        assert executor.prompt_builder is builder


# ---------------------------------------------------------------------------
# DEFAULT_BATCH_SIZE constant
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_batch_size_constant(self):
        assert DEFAULT_BATCH_SIZE == 100

    def test_missing_batch_size_uses_default(self):
        s = _settings()
        del s["batch_size"]
        executor = BatchExecutor(s, client=MagicMock())
        assert executor.batch_size == DEFAULT_BATCH_SIZE


# ---------------------------------------------------------------------------
# Logging (smoke test — ensure no crash)
# ---------------------------------------------------------------------------


class TestLogging:
    def test_report_does_not_raise_on_mixed_result(self):
        executor = BatchExecutor(_settings(), client=MagicMock())
        result = BatchResult(
            questions=[_mock_generated_question()],
            failed_batches=[FailedBatch(batch_index=1, item_count=3, error="oops")],
            total_batches=2,
            successful_batches=1,
        )
        executor._report(result)
