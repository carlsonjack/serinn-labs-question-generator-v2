"""Tests for QA summary report (EPIC 6, Task 6.3)."""

from __future__ import annotations

import io
import logging

import pytest

from core.dedup import DeduplicationResult
from core.generation.row_assembler import OutputRow
from core.generation.token_tracker import RunCostSummary
from core.qa_summary import (
    QASummary,
    _HEADER,
    _SEPARATOR,
    build_qa_summary,
    format_qa_summary,
    print_qa_summary,
)
from core.schema_validator import RowValidationError, ValidationResult


def _make_row(**overrides: object) -> OutputRow:
    defaults = {
        "topic_import_id": "mlb-regular-season",
        "subcategory": "MLB",
        "event": "Mets vs Yankees",
        "question": "Who will win?",
        "answer_type": "yes_no",
        "answer_options": "Yes||No",
        "start_date": "2026-05-14T21:40:00",
        "expiration_date": "2026-05-15T21:40:00",
        "resolution_date": "2026-05-16T01:40:00",
        "priority": 1,
    }
    defaults.update(overrides)
    return OutputRow(**defaults)


def _validation(*, valid: int = 0, invalid: int = 0) -> ValidationResult:
    return ValidationResult(
        valid_rows=[_make_row(question=f"q{i}") for i in range(valid)],
        invalid_rows=[
            RowValidationError(row=_make_row(question=f"bad{i}"), reasons=["test"])
            for i in range(invalid)
        ],
    )


def _dedup(
    *,
    clean: int = 0,
    flagged: int = 0,
    exact_removed: int = 0,
) -> DeduplicationResult:
    return DeduplicationResult(
        clean_rows=[_make_row(question=f"c{i}") for i in range(clean)],
        flagged_rows=[_make_row(question=f"f{i}") for i in range(flagged)],
        flagged_pairs=[],
        exact_duplicates_removed=exact_removed,
        near_duplicates_flagged=flagged,
    )


def _cost(usd: float = 0.0042, model: str = "gpt-4o") -> RunCostSummary:
    return RunCostSummary(
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        estimated_cost_usd=usd,
        model=model,
    )


# ── QASummary dataclass ──────────────────────────────────────────────────


class TestQASummary:
    def test_has_cost_true(self) -> None:
        s = QASummary(10, 8, 2, 1, 0, 0.005)
        assert s.has_cost is True

    def test_has_cost_false_when_none(self) -> None:
        s = QASummary(10, 8, 2, 1, 0, None)
        assert s.has_cost is False

    def test_has_cost_true_when_zero(self) -> None:
        s = QASummary(10, 8, 2, 1, 0, 0.0)
        assert s.has_cost is True

    def test_fields_accessible(self) -> None:
        s = QASummary(100, 90, 10, 5, 3, 1.23)
        assert s.total_rows_generated == 100
        assert s.rows_passed_validation == 90
        assert s.rows_failed_validation == 10
        assert s.rows_flagged_near_duplicate == 5
        assert s.exact_duplicates_removed == 3
        assert s.estimated_cost_usd == 1.23


# ── build_qa_summary ─────────────────────────────────────────────────────


class TestBuildQaSummary:
    def test_all_valid_no_dupes(self) -> None:
        s = build_qa_summary(_validation(valid=20), _dedup(clean=20))
        assert s.total_rows_generated == 20
        assert s.rows_passed_validation == 20
        assert s.rows_failed_validation == 0
        assert s.rows_flagged_near_duplicate == 0
        assert s.exact_duplicates_removed == 0
        assert s.estimated_cost_usd is None

    def test_mixed_validation(self) -> None:
        s = build_qa_summary(
            _validation(valid=15, invalid=5),
            _dedup(clean=15, flagged=2, exact_removed=1),
        )
        assert s.total_rows_generated == 20
        assert s.rows_passed_validation == 15
        assert s.rows_failed_validation == 5
        assert s.rows_flagged_near_duplicate == 2
        assert s.exact_duplicates_removed == 1

    def test_with_cost(self) -> None:
        cost = _cost(usd=0.0042)
        s = build_qa_summary(_validation(valid=10), _dedup(clean=10), cost)
        assert s.estimated_cost_usd == pytest.approx(0.0042)

    def test_without_cost(self) -> None:
        s = build_qa_summary(_validation(valid=10), _dedup(clean=10), None)
        assert s.estimated_cost_usd is None

    def test_empty_run(self) -> None:
        s = build_qa_summary(_validation(), _dedup())
        assert s.total_rows_generated == 0
        assert s.rows_passed_validation == 0
        assert s.rows_failed_validation == 0

    def test_all_invalid(self) -> None:
        s = build_qa_summary(_validation(invalid=10), _dedup())
        assert s.rows_passed_validation == 0
        assert s.rows_failed_validation == 10


# ── format_qa_summary ────────────────────────────────────────────────────


class TestFormatQaSummary:
    def test_contains_separator(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.005))
        assert text.startswith(_SEPARATOR)
        assert text.endswith(_SEPARATOR)

    def test_contains_header(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.005))
        assert _HEADER in text

    def test_shows_total_rows(self) -> None:
        text = format_qa_summary(QASummary(42, 30, 12, 3, 2, None))
        assert "42" in text

    def test_shows_valid_count(self) -> None:
        text = format_qa_summary(QASummary(42, 30, 12, 3, 2, None))
        assert "30" in text

    def test_shows_error_count(self) -> None:
        text = format_qa_summary(QASummary(42, 30, 12, 3, 2, None))
        assert "12" in text

    def test_shows_near_duplicate_count(self) -> None:
        text = format_qa_summary(QASummary(42, 30, 12, 3, 2, None))
        assert "3" in text

    def test_shows_exact_dupes_removed(self) -> None:
        text = format_qa_summary(QASummary(42, 30, 12, 3, 2, None))
        assert "2" in text

    def test_shows_cost_when_present(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.0042))
        assert "$0.0042 USD" in text

    def test_shows_na_when_no_cost(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, None))
        assert "N/A" in text

    def test_shows_zero_cost(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.0))
        assert "$0.0000 USD" in text

    def test_label_rows_passed_validation(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, None))
        assert "Rows passed validation" in text

    def test_label_rows_written_to_errors(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, None))
        assert "Rows written to errors" in text

    def test_label_near_duplicate(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, None))
        assert "near-duplicate" in text

    def test_label_estimated_api_cost(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.01))
        assert "Estimated API cost" in text

    def test_multiline_output(self) -> None:
        text = format_qa_summary(QASummary(10, 8, 2, 1, 0, 0.01))
        lines = text.strip().split("\n")
        assert len(lines) >= 8


# ── print_qa_summary ─────────────────────────────────────────────────────


class TestPrintQaSummary:
    def test_writes_to_custom_file(self) -> None:
        buf = io.StringIO()
        print_qa_summary(_validation(valid=5), _dedup(clean=5), file=buf)
        output = buf.getvalue()
        assert "5" in output
        assert _SEPARATOR in output

    def test_returns_summary_object(self) -> None:
        buf = io.StringIO()
        result = print_qa_summary(
            _validation(valid=10, invalid=3),
            _dedup(clean=10, flagged=2, exact_removed=1),
            file=buf,
        )
        assert isinstance(result, QASummary)
        assert result.total_rows_generated == 13
        assert result.rows_passed_validation == 10
        assert result.rows_failed_validation == 3
        assert result.rows_flagged_near_duplicate == 2
        assert result.exact_duplicates_removed == 1

    def test_with_cost_object(self) -> None:
        buf = io.StringIO()
        result = print_qa_summary(
            _validation(valid=10),
            _dedup(clean=10),
            _cost(usd=0.0099),
            file=buf,
        )
        assert result.estimated_cost_usd == pytest.approx(0.0099)
        assert "$0.0099 USD" in buf.getvalue()

    def test_without_cost_shows_na(self) -> None:
        buf = io.StringIO()
        print_qa_summary(_validation(valid=5), _dedup(clean=5), file=buf)
        assert "N/A" in buf.getvalue()

    def test_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        buf = io.StringIO()
        with caplog.at_level(logging.INFO, logger="core.qa_summary"):
            print_qa_summary(
                _validation(valid=7, invalid=2),
                _dedup(clean=7, flagged=1),
                file=buf,
            )
        assert any("QA summary" in r.message for r in caplog.records)

    def test_log_contains_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        buf = io.StringIO()
        with caplog.at_level(logging.INFO, logger="core.qa_summary"):
            print_qa_summary(
                _validation(valid=7, invalid=2),
                _dedup(clean=7, flagged=1, exact_removed=3),
                file=buf,
            )
        log_text = " ".join(r.message for r in caplog.records)
        assert "generated: 9" in log_text
        assert "valid: 7" in log_text
        assert "errors: 2" in log_text

    def test_empty_run(self) -> None:
        buf = io.StringIO()
        result = print_qa_summary(_validation(), _dedup(), file=buf)
        assert result.total_rows_generated == 0
        output = buf.getvalue()
        assert _SEPARATOR in output

    def test_defaults_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_qa_summary(_validation(valid=3), _dedup(clean=3))
        captured = capsys.readouterr()
        assert _SEPARATOR in captured.out
        assert "3" in captured.out


# ── Integration-style: round-trip from result objects ────────────────────


class TestIntegration:
    def test_full_pipeline_summary(self) -> None:
        validation = _validation(valid=50, invalid=5)
        dedup = _dedup(clean=45, flagged=5, exact_removed=3)
        cost = _cost(usd=0.125)

        buf = io.StringIO()
        result = print_qa_summary(validation, dedup, cost, file=buf)
        output = buf.getvalue()

        assert result.total_rows_generated == 55
        assert result.rows_passed_validation == 50
        assert result.rows_failed_validation == 5
        assert result.rows_flagged_near_duplicate == 5
        assert result.exact_duplicates_removed == 3
        assert result.estimated_cost_usd == pytest.approx(0.125)

        assert "$0.1250 USD" in output
        assert "55" in output
        assert "50" in output

    def test_large_numbers_format(self) -> None:
        validation = _validation(valid=10000, invalid=500)
        dedup = _dedup(clean=9500, flagged=500, exact_removed=200)
        cost = _cost(usd=45.6789)

        buf = io.StringIO()
        result = print_qa_summary(validation, dedup, cost, file=buf)
        output = buf.getvalue()

        assert result.total_rows_generated == 10500
        assert "$45.6789 USD" in output
