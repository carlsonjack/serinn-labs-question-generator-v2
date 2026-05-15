"""Tests for schema validation (EPIC 6, Task 6.2)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow
from core.schema_validator import (
    DATE_FIELDS,
    REQUIRED_FIELDS,
    VALID_ANSWER_TYPES,
    RowValidationError,
    ValidationResult,
    _is_valid_iso8601,
    validate_row,
    validate_rows,
    write_errors_csv,
)


def _make_row(**overrides: object) -> OutputRow:
    """Build a valid OutputRow, applying *overrides* to any field."""
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


# ── ISO 8601 helper ──────────────────────────────────────────────────────


class TestIsValidIso8601:
    def test_datetime_no_tz(self) -> None:
        assert _is_valid_iso8601("2026-05-15T21:40:00") is True

    def test_date_only(self) -> None:
        assert _is_valid_iso8601("2026-05-15") is True

    def test_datetime_with_tz(self) -> None:
        assert _is_valid_iso8601("2026-05-15T21:40:00+00:00") is True

    def test_garbage(self) -> None:
        assert _is_valid_iso8601("not-a-date") is False

    def test_empty_string(self) -> None:
        assert _is_valid_iso8601("") is False

    def test_partial_date(self) -> None:
        assert _is_valid_iso8601("2026-13-01") is False

    def test_valid_leap_day(self) -> None:
        assert _is_valid_iso8601("2024-02-29T00:00:00") is True

    def test_invalid_leap_day(self) -> None:
        assert _is_valid_iso8601("2025-02-29T00:00:00") is False


# ── Single-row validation ────────────────────────────────────────────────


class TestValidateRow:
    def test_valid_row_no_errors(self) -> None:
        assert validate_row(_make_row()) == []

    def test_missing_required_field_topic_import_id(self) -> None:
        reasons = validate_row(_make_row(topic_import_id=""))
        assert any("topic_import_id" in r for r in reasons)

    def test_missing_required_field_subcategory(self) -> None:
        reasons = validate_row(_make_row(subcategory=""))
        assert any("subcategory" in r for r in reasons)

    def test_missing_required_field_event(self) -> None:
        reasons = validate_row(_make_row(event=""))
        assert any("event" in r for r in reasons)

    def test_missing_required_field_question(self) -> None:
        reasons = validate_row(_make_row(question=""))
        assert any("question" in r for r in reasons)

    def test_missing_required_field_answer_options(self) -> None:
        reasons = validate_row(_make_row(answer_options=""))
        assert any("answer_options" in r for r in reasons)

    def test_whitespace_only_counts_as_missing(self) -> None:
        reasons = validate_row(_make_row(topic_import_id="   "))
        assert any("topic_import_id" in r for r in reasons)

    def test_invalid_answer_type(self) -> None:
        reasons = validate_row(_make_row(answer_type="free_text"))
        assert any("answer_type" in r for r in reasons)

    def test_valid_answer_type_yes_no(self) -> None:
        reasons = validate_row(_make_row(answer_type="yes_no"))
        assert not any("answer_type" in r for r in reasons)

    def test_valid_answer_type_multiple_choice(self) -> None:
        reasons = validate_row(_make_row(answer_type="multiple_choice"))
        assert not any("answer_type" in r for r in reasons)

    def test_invalid_date_start(self) -> None:
        reasons = validate_row(_make_row(start_date="garbage"))
        assert any("start_date" in r for r in reasons)

    def test_invalid_date_expiration(self) -> None:
        reasons = validate_row(_make_row(expiration_date="not-a-date"))
        assert any("expiration_date" in r for r in reasons)

    def test_invalid_date_resolution(self) -> None:
        reasons = validate_row(_make_row(resolution_date="99-99-99"))
        assert any("resolution_date" in r for r in reasons)

    def test_valid_dates_pass(self) -> None:
        row = _make_row(
            start_date="2026-05-14T21:40:00",
            expiration_date="2026-05-15T21:40:00",
            resolution_date="2026-05-16T01:40:00",
        )
        assert validate_row(row) == []

    def test_valid_priority_integer(self) -> None:
        assert validate_row(_make_row(priority=1)) == []

    def test_valid_priority_blank(self) -> None:
        assert validate_row(_make_row(priority="")) == []

    def test_valid_priority_zero(self) -> None:
        assert validate_row(_make_row(priority=0)) == []

    @pytest.mark.parametrize("bad_priority", ["true", True])
    def test_priority_legacy_truthy_value_fails(self, bad_priority: object) -> None:
        reasons = validate_row(_make_row(priority=bad_priority))
        assert any("priority" in r and "integer or blank" in r for r in reasons)

    def test_priority_negative_integer_fails(self) -> None:
        reasons = validate_row(_make_row(priority=-1))
        assert any("priority" in r and "non-negative integer or blank" in r for r in reasons)

    def test_multiple_failures_collected(self) -> None:
        reasons = validate_row(
            _make_row(
                topic_import_id="",
                answer_type="bad",
                start_date="nope",
                priority="maybe",
            )
        )
        assert len(reasons) >= 4

    def test_answer_type_case_sensitive(self) -> None:
        reasons = validate_row(_make_row(answer_type="Yes_No"))
        assert any("answer_type" in r for r in reasons)

    def test_priority_legacy_truthy_string_case_insensitive_invalid(self) -> None:
        reasons = validate_row(_make_row(priority="True"))
        assert any("priority" in r for r in reasons)


# ── Batch validation ─────────────────────────────────────────────────────


class TestValidateRows:
    def test_all_valid(self) -> None:
        rows = [_make_row(), _make_row(question="Will it rain?")]
        result = validate_rows(rows)
        assert result.valid_count == 2
        assert result.invalid_count == 0

    def test_all_invalid(self) -> None:
        rows = [
            _make_row(answer_type="bad"),
            _make_row(priority="yes"),
        ]
        result = validate_rows(rows)
        assert result.valid_count == 0
        assert result.invalid_count == 2

    def test_mixed_valid_and_invalid(self) -> None:
        rows = [
            _make_row(),
            _make_row(answer_type="bad"),
            _make_row(question="Another valid?"),
        ]
        result = validate_rows(rows)
        assert result.valid_count == 2
        assert result.invalid_count == 1

    def test_empty_input(self) -> None:
        result = validate_rows([])
        assert result.total_input == 0
        assert result.valid_count == 0
        assert result.invalid_count == 0

    def test_total_input_property(self) -> None:
        rows = [_make_row(), _make_row(answer_type="bad")]
        result = validate_rows(rows)
        assert result.total_input == 2

    def test_invalid_rows_contain_reasons(self) -> None:
        rows = [_make_row(start_date="invalid")]
        result = validate_rows(rows)
        assert result.invalid_count == 1
        assert len(result.invalid_rows[0].reasons) > 0

    def test_valid_rows_are_originals(self) -> None:
        original = _make_row()
        result = validate_rows([original])
        assert result.valid_rows[0] is original


# ── ValidationResult dataclass ───────────────────────────────────────────


class TestValidationResult:
    def test_defaults(self) -> None:
        r = ValidationResult()
        assert r.valid_rows == []
        assert r.invalid_rows == []
        assert r.total_input == 0

    def test_properties(self) -> None:
        r = ValidationResult(
            valid_rows=[_make_row()],
            invalid_rows=[RowValidationError(row=_make_row(), reasons=["bad"])],
        )
        assert r.valid_count == 1
        assert r.invalid_count == 1
        assert r.total_input == 2


# ── Error CSV writer ─────────────────────────────────────────────────────


class TestWriteErrorsCsv:
    def test_file_creation(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        errors = [RowValidationError(row=_make_row(), reasons=["bad field"])]
        result_path = write_errors_csv(errors, output_path=out)
        assert result_path.exists()
        assert result_path == out

    def test_columns(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        write_errors_csv(
            [RowValidationError(row=_make_row(), reasons=["oops"])],
            output_path=out,
        )
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == OUTPUT_COLUMNS + ["reason"]

    def test_row_count(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        errors = [
            RowValidationError(row=_make_row(), reasons=["a"]),
            RowValidationError(row=_make_row(question="Q2"), reasons=["b"]),
        ]
        write_errors_csv(errors, output_path=out)
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2

    def test_reason_content(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        write_errors_csv(
            [RowValidationError(row=_make_row(), reasons=["bad type", "bad date"])],
            output_path=out,
        )
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["reason"] == "bad type; bad date"

    def test_empty_input(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        write_errors_csv([], output_path=out)
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 0

    def test_nested_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "errors.csv"
        write_errors_csv(
            [RowValidationError(row=_make_row(), reasons=["err"])],
            output_path=out,
        )
        assert out.exists()

    def test_row_data_matches_output_columns(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        row = _make_row(subcategory="NBA", event="Celtics vs Lakers")
        write_errors_csv(
            [RowValidationError(row=row, reasons=["test"])],
            output_path=out,
        )
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["subcategory"] == "NBA"
        assert rows[0]["event"] == "Celtics vs Lakers"

    def test_single_reason_no_semicolon(self, tmp_path: Path) -> None:
        out = tmp_path / "errors.csv"
        write_errors_csv(
            [RowValidationError(row=_make_row(), reasons=["one issue"])],
            output_path=out,
        )
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert ";" not in rows[0]["reason"]


# ── Constants ────────────────────────────────────────────────────────────


class TestConstants:
    def test_required_fields_exclude_blankable_priority(self) -> None:
        assert REQUIRED_FIELDS == [col for col in OUTPUT_COLUMNS if col != "priority"]

    def test_valid_answer_types(self) -> None:
        assert VALID_ANSWER_TYPES == {"yes_no", "multiple_choice"}

    def test_date_fields(self) -> None:
        assert DATE_FIELDS == ["start_date", "expiration_date", "resolution_date"]
