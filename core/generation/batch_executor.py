"""Batch executor for OpenAI question generation (EPIC 5, Task 5.2).

Groups PromptItems into configurable batches, sends one API call per batch
using structured-output parsing, and collects results.  Failed batches are
logged and skipped so that one transient error does not abort the entire run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

from .prompt_builder import (
    GeneratedQuestion,
    GeneratedQuestionBatch,
    PromptBuilder,
    PromptConfig,
    PromptItem,
)
from .token_tracker import (
    RunCostSummary,
    TokenUsage,
    build_cost_summary,
    extract_token_usage,
    log_cost_summary,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FailedBatch:
    """Metadata for a batch whose API call failed."""

    batch_index: int
    item_count: int
    error: str


@dataclass
class BatchResult:
    """Aggregated result of processing all batches."""

    questions: list[GeneratedQuestion] = field(default_factory=list)
    failed_batches: list[FailedBatch] = field(default_factory=list)
    total_batches: int = 0
    successful_batches: int = 0
    token_usages: list[TokenUsage] = field(default_factory=list)
    cost_summary: RunCostSummary | None = None

    @property
    def all_succeeded(self) -> bool:
        return len(self.failed_batches) == 0

    @property
    def total_questions(self) -> int:
        return len(self.questions)


# ---------------------------------------------------------------------------
# Batch executor
# ---------------------------------------------------------------------------


class BatchExecutor:
    """Chunks prompt items and sends one OpenAI API call per batch.

    Parameters
    ----------
    settings:
        The global settings dict (from ``load_settings``).  Used to read
        ``batch_size``, ``model``, and ``openai_api_key``.
    prompt_builder:
        Optional pre-configured ``PromptBuilder``.  A default one is created
        if not supplied.
    client:
        Optional pre-configured ``OpenAI`` client.  Useful for testing.
        When *None* the executor builds its own client from the API key in
        *settings*.
    """

    def __init__(
        self,
        settings: dict[str, Any],
        prompt_builder: PromptBuilder | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.batch_size: int = int(settings.get("batch_size", DEFAULT_BATCH_SIZE))
        self.model: str = settings.get("model", "gpt-4o")
        self.prompt_builder = prompt_builder or PromptBuilder()
        self._client = client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            api_key = self.settings.get("openai_api_key", "")
            if not api_key:
                raise ValueError(
                    "openai_api_key is not set in settings or environment"
                )
            self._client = OpenAI(api_key=api_key)
        return self._client

    # -- public API --------------------------------------------------------

    def execute(
        self,
        items: list[PromptItem],
        *,
        on_batch_done: Callable[[int, int], None] | None = None,
    ) -> BatchResult:
        """Run generation across all items, batched by ``self.batch_size``.

        Returns a :class:`BatchResult` that contains every successfully
        generated question **and** metadata for any batches that failed.

        If *on_batch_done* is set, it is invoked as ``on_batch_done(index, total)``
        after each batch attempt (1-based *index*, *total* batch count).
        """
        if not items:
            return BatchResult()

        batches = self._chunk(items)
        result = BatchResult(total_batches=len(batches))
        total = len(batches)

        for idx, batch in enumerate(batches):
            try:
                questions, usage = self._execute_batch(batch, idx)
                result.questions.extend(questions)
                result.token_usages.append(usage)
                result.successful_batches += 1
                logger.info(
                    "Batch %d/%d succeeded — %d question(s)",
                    idx + 1,
                    result.total_batches,
                    len(questions),
                )
            except Exception as exc:
                failure = FailedBatch(
                    batch_index=idx,
                    item_count=len(batch),
                    error=str(exc),
                )
                result.failed_batches.append(failure)
                logger.error(
                    "Batch %d/%d failed (%d items): %s",
                    idx + 1,
                    result.total_batches,
                    len(batch),
                    exc,
                )
            if on_batch_done is not None:
                on_batch_done(idx + 1, total)

        result.cost_summary = build_cost_summary(
            result.token_usages, self.model, self.settings
        )
        self._report(result)
        return result

    # -- internals ---------------------------------------------------------

    def _chunk(self, items: list[PromptItem]) -> list[list[PromptItem]]:
        """Split *items* into sub-lists of at most ``self.batch_size``."""
        size = max(1, self.batch_size)
        return [items[i : i + size] for i in range(0, len(items), size)]

    def _execute_batch(
        self, batch: list[PromptItem], batch_index: int
    ) -> tuple[list[GeneratedQuestion], TokenUsage]:
        """Send a single batch to the OpenAI API and parse the response."""
        messages = self.prompt_builder.build_prompt(batch)

        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=self.prompt_builder.response_schema,
        )

        usage = extract_token_usage(response)

        parsed: GeneratedQuestionBatch | None = response.choices[0].message.parsed

        if parsed is None:
            refusal = getattr(response.choices[0].message, "refusal", None)
            raise RuntimeError(
                f"Batch {batch_index}: model returned no parsed output"
                + (f" (refusal: {refusal})" if refusal else "")
            )

        return parsed.questions, usage

    def _report(self, result: BatchResult) -> None:
        """Log a summary after all batches have been processed."""
        logger.info(
            "Generation complete — %d batch(es), %d succeeded, %d failed, %d question(s) total",
            result.total_batches,
            result.successful_batches,
            len(result.failed_batches),
            result.total_questions,
        )
        for fb in result.failed_batches:
            logger.warning(
                "  Failed batch %d (%d items): %s",
                fb.batch_index,
                fb.item_count,
                fb.error,
            )
        if result.cost_summary is not None:
            log_cost_summary(result.cost_summary)
