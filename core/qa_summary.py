"""QA summary report (EPIC 6, Task 6.3).

After each generation run, prints a concise console summary covering row
counts, validation outcomes, deduplication results, and estimated API cost.
All inputs are the structured result objects already produced by the pipeline
so that calling code needs only a single ``print_qa_summary(…)`` call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TextIO

from core.dedup import DeduplicationResult
from core.generation.token_tracker import RunCostSummary
from core.schema_validator import ValidationResult

logger = logging.getLogger(__name__)

_SEPARATOR = "=" * 52
_HEADER = " QA Summary Report"


@dataclass
class QASummary:
    """Aggregated statistics for a single pipeline run."""

    total_rows_generated: int
    rows_passed_validation: int
    rows_failed_validation: int
    rows_flagged_near_duplicate: int
    exact_duplicates_removed: int
    estimated_cost_usd: float | None

    @property
    def has_cost(self) -> bool:
        return self.estimated_cost_usd is not None


def build_qa_summary(
    validation: ValidationResult,
    dedup: DeduplicationResult,
    cost: RunCostSummary | None = None,
) -> QASummary:
    """Construct a :class:`QASummary` from pipeline result objects.

    Parameters
    ----------
    validation:
        Result of ``validate_rows`` — provides valid/invalid counts.
    dedup:
        Result of ``deduplicate`` — provides near-duplicate and exact-
        duplicate counts.
    cost:
        Optional :class:`RunCostSummary` from the generation step.
        Pass ``None`` when cost tracking is unavailable.
    """
    return QASummary(
        total_rows_generated=validation.total_input,
        rows_passed_validation=validation.valid_count,
        rows_failed_validation=validation.invalid_count,
        rows_flagged_near_duplicate=dedup.near_duplicates_flagged,
        exact_duplicates_removed=dedup.exact_duplicates_removed,
        estimated_cost_usd=cost.estimated_cost_usd if cost else None,
    )


def format_qa_summary(summary: QASummary) -> str:
    """Return a multi-line, human-readable summary string."""
    lines = [
        _SEPARATOR,
        _HEADER,
        _SEPARATOR,
        f"  Total rows generated        : {summary.total_rows_generated}",
        f"  Rows passed validation       : {summary.rows_passed_validation}",
        f"  Rows written to errors       : {summary.rows_failed_validation}",
        f"  Rows flagged as near-duplicate: {summary.rows_flagged_near_duplicate}",
        f"  Exact duplicates removed     : {summary.exact_duplicates_removed}",
    ]
    if summary.has_cost:
        lines.append(
            f"  Estimated API cost           : ${summary.estimated_cost_usd:.4f} USD"
        )
    else:
        lines.append(
            "  Estimated API cost           : N/A"
        )
    lines.append(_SEPARATOR)
    return "\n".join(lines)


def print_qa_summary(
    validation: ValidationResult,
    dedup: DeduplicationResult,
    cost: RunCostSummary | None = None,
    *,
    file: TextIO | None = None,
) -> QASummary:
    """Build, log, and print the QA summary report.

    Convenience entry point that combines :func:`build_qa_summary` and
    :func:`format_qa_summary`, writes the result to *file* (defaults to
    ``sys.stdout``), and also emits a structured ``INFO`` log.

    Returns the :class:`QASummary` so callers can inspect the numbers
    programmatically.
    """
    import sys

    summary = build_qa_summary(validation, dedup, cost)
    text = format_qa_summary(summary)

    dest = file if file is not None else sys.stdout
    print(text, file=dest)

    logger.info(
        "QA summary — generated: %d, valid: %d, errors: %d, "
        "near-dupes: %d, exact-dupes removed: %d, cost: %s",
        summary.total_rows_generated,
        summary.rows_passed_validation,
        summary.rows_failed_validation,
        summary.rows_flagged_near_duplicate,
        summary.exact_duplicates_removed,
        f"${summary.estimated_cost_usd:.4f}"
        if summary.has_cost
        else "N/A",
    )

    return summary
