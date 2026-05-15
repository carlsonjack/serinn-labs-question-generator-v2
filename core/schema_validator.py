"""Schema validation layer (EPIC 6, Task 6.2).

Validates every output row against the expected CSV schema before final export.
Rows that fail validation are separated and written to ``outputs/errors.csv``
with a human-readable ``reason`` column explaining the failure.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from core.csv_export import CSV_WRITE_ENCODING
from core.generation.content import ImportQuestionRow
from core.generation.stocks import StockQuestionRow
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow

logger = logging.getLogger(__name__)

REQUIRED_FIELDS: list[str] = [col for col in OUTPUT_COLUMNS if col != "priority"]
"""Columns in the output schema that must be non-empty."""

VALID_ANSWER_TYPES: frozenset[str] = frozenset({"yes_no", "multiple_choice"})
DATE_FIELDS: list[str] = ["start_date", "expiration_date", "resolution_date"]


@dataclass
class RowValidationError:
    """A single validation failure for one row."""

    row: OutputRow
    reasons: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Outcome of running schema validation on a batch of rows."""

    valid_rows: list[OutputRow] = field(default_factory=list)
    invalid_rows: list[RowValidationError] = field(default_factory=list)

    @property
    def total_input(self) -> int:
        return len(self.valid_rows) + len(self.invalid_rows)

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_rows)


def _is_valid_iso8601(value: str) -> bool:
    """Return True if *value* parses as a valid ISO 8601 datetime string."""
    return _parse_iso8601(value) is not None


def _parse_iso8601(value: str) -> datetime | None:
    """Return a parsed ISO 8601 datetime, or ``None`` when invalid."""

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def validate_row(row: OutputRow) -> list[str]:
    """Validate a single row and return a list of failure reasons (empty = valid)."""
    reasons: list[str] = []
    row_dict = row.to_dict()

    for col in REQUIRED_FIELDS:
        val = row_dict.get(col, "")
        if val is None or str(val).strip() == "":
            reasons.append(f"Missing required field: {col}")

    if row.answer_type not in VALID_ANSWER_TYPES:
        reasons.append(
            f"Invalid answer_type: {row.answer_type!r} "
            f"(expected one of {sorted(VALID_ANSWER_TYPES)})"
        )

    for date_col in DATE_FIELDS:
        date_val = row_dict.get(date_col, "")
        if date_val and not _is_valid_iso8601(str(date_val)):
            reasons.append(
                f"Invalid ISO 8601 date in {date_col}: {date_val!r}"
            )

    priority_reason = _validate_priority(row.priority)
    if priority_reason is not None:
        reasons.append(priority_reason)

    return reasons


def _validate_priority(value: Any) -> str | None:
    if value == "":
        return None
    if isinstance(value, bool):
        return "Invalid priority: priority must be an integer or blank"
    if isinstance(value, int):
        if value >= 0:
            return None
        return "Invalid priority: priority must be a non-negative integer or blank"
    return "Invalid priority: priority must be an integer or blank"


def validate_rows(rows: Sequence[OutputRow]) -> ValidationResult:
    """Run schema validation on all rows and partition into valid/invalid.

    Parameters
    ----------
    rows:
        Output rows to validate.

    Returns
    -------
    ValidationResult:
        Contains ``valid_rows`` that passed all checks and ``invalid_rows``
        with attached failure reasons.
    """
    result = ValidationResult()

    for row in rows:
        reasons = validate_row(row)
        if reasons:
            result.invalid_rows.append(RowValidationError(row=row, reasons=reasons))
            logger.debug("Row failed validation: %s", reasons)
        else:
            result.valid_rows.append(row)

    if result.invalid_rows:
        logger.info(
            "Schema validation: %d valid, %d invalid out of %d total",
            result.valid_count,
            result.invalid_count,
            result.total_input,
        )
    else:
        logger.info(
            "Schema validation: all %d rows passed", result.total_input
        )

    return result


def validate_import_row(row: ImportQuestionRow) -> list[str]:
    """Validate one deterministic import row against Jim's titled CSV contract."""

    reasons: list[str] = []
    if not row.topic_import_id.strip():
        reasons.append("Missing required field: Topic Import ID")
    if not row.question.strip():
        reasons.append("Missing required field: Question")
    if row.answer_type not in VALID_ANSWER_TYPES:
        reasons.append(f"Invalid Answer Type: {row.answer_type!r}")
    if row.answer_type == "multiple_choice" and "||" not in row.answer_options:
        reasons.append("Multiple choice rows require ||-delimited Answer Options")
    if row.answer_type == "yes_no" and row.answer_options.strip():
        reasons.append("yes_no import rows must leave Answer Options blank")
    for label, value in (
        ("Start Date", row.start_date),
        ("Expiration Date", row.expiration_date),
        ("Resolution Date", row.resolution_date),
    ):
        if not value or not _is_valid_iso8601(value):
            reasons.append(f"Invalid ISO 8601 date in {label}: {value!r}")
    priority_reason = _validate_priority(row.priority)
    if priority_reason is not None:
        reasons.append(priority_reason)
    unresolved_chars = "{}[]"
    if any(ch in row.question or ch in row.answer_options for ch in unresolved_chars):
        reasons.append("Unresolved placeholder remains in import row")
    return reasons


def validate_stock_row(row: StockQuestionRow) -> list[str]:
    """Validate one stock import row against Jim's MVP CSV contract."""

    return validate_import_row(row)


def validate_stock_rows(rows: Sequence[StockQuestionRow]) -> list[tuple[StockQuestionRow, list[str]]]:
    """Return ``(row, reasons)`` pairs for invalid stock rows."""

    return [(row, reasons) for row in rows if (reasons := validate_stock_row(row))]


def validate_import_rows(rows: Sequence[ImportQuestionRow]) -> list[tuple[ImportQuestionRow, list[str]]]:
    """Return ``(row, reasons)`` pairs for invalid deterministic import rows."""

    return [(row, reasons) for row in rows if (reasons := validate_import_row(row))]


def write_errors_csv(
    errors: Sequence[RowValidationError],
    output_path: str | Path = "outputs/errors.csv",
) -> Path:
    """Write invalid rows to a CSV file with a ``reason`` column.

    The CSV contains the standard output columns plus a ``reason`` column
    listing every validation failure for that row (semicolon-separated when
    there are multiple failures).
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = OUTPUT_COLUMNS + ["reason"]

    with path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for error in errors:
            row_dict: dict[str, Any] = error.row.to_dict()
            row_dict["reason"] = "; ".join(error.reasons)
            writer.writerow(row_dict)

    logger.info("Wrote %d error row(s) to %s", len(errors), path)
    return path
