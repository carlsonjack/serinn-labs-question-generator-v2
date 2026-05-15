"""Tests for main CSV export (EPIC 7)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from core.csv_export import (
    CSV_WRITE_ENCODING,
    DEFAULT_OUTPUT_DIR,
    build_generated_csv_path,
    sanitize_filename_component,
    write_generated_csv,
    write_generated_csv_auto,
)
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow


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


class TestSanitizeFilenameComponent:
    def test_mlb_unchanged(self) -> None:
        assert sanitize_filename_component("MLB") == "MLB"

    def test_spaces_to_underscore(self) -> None:
        assert sanitize_filename_component("MLB Pro") == "MLB_Pro"

    def test_strips_unsafe_chars(self) -> None:
        assert sanitize_filename_component("foo/bar:baz") == "foo_bar_baz"

    def test_empty_becomes_unknown(self) -> None:
        assert sanitize_filename_component("   ") == "unknown"


class TestBuildGeneratedCsvPath:
    def test_pattern_and_parts(self, tmp_path: Path) -> None:
        fixed = datetime(2026, 4, 17, 14, 30, 45, 123456)
        p = build_generated_csv_path(
            "MLB",
            "2026-05-15",
            "2026-06-01",
            output_dir=tmp_path,
            now=fixed,
        )
        assert p.parent == tmp_path
        assert p.name == (
            "generated_MLB_2026-05-15_to_2026-06-01_20260417_143045_123456.csv"
        )

    def test_sanitized_subcategory(self, tmp_path: Path) -> None:
        fixed = datetime(2026, 1, 1, 0, 0, 0, 0)
        p = build_generated_csv_path(
            "Big League",
            "2026-05-15",
            "2026-06-01",
            output_dir=tmp_path,
            now=fixed,
        )
        assert "Big_League" in p.name

    def test_slash_in_dates_normalized(self, tmp_path: Path) -> None:
        fixed = datetime(2026, 1, 1, 0, 0, 0, 0)
        p = build_generated_csv_path(
            "MLB",
            "2026/05/15",
            "2026/06/01",
            output_dir=tmp_path,
            now=fixed,
        )
        assert "2026-05-15_to_2026-06-01" in p.name

    def test_different_now_different_paths(self, tmp_path: Path) -> None:
        a = build_generated_csv_path(
            "MLB",
            "2026-05-15",
            "2026-06-01",
            output_dir=tmp_path,
            now=datetime(2026, 4, 17, 10, 0, 0, 0),
        )
        b = build_generated_csv_path(
            "MLB",
            "2026-05-15",
            "2026-06-01",
            output_dir=tmp_path,
            now=datetime(2026, 4, 17, 10, 0, 0, 1),
        )
        assert a != b


class TestWriteGeneratedCsv:
    def test_columns(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        write_generated_csv([_make_row()], out)
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames) == [
                "topic_import_id",
                "subcategory",
                "event",
                "question",
                "answer_type",
                "answer_options",
                "start_date",
                "expiration_date",
                "resolution_date",
                "priority",
            ]

    def test_row_values(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        write_generated_csv([_make_row(question="Q1")], out)
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["question"] == "Q1"
        assert rows[0]["subcategory"] == "MLB"

    def test_utf8_non_ascii(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        write_generated_csv(
            [_make_row(question="It\u2019s a test")],
            out,
        )
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["question"] == "It\u2019s a test"

    def test_no_extra_index_column(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        write_generated_csv([_make_row()], out)
        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames is not None
            assert not any(
                name is None or name.startswith("Unnamed") for name in reader.fieldnames
            )

    def test_creates_nested_parent(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deep" / "out.csv"
        write_generated_csv([_make_row()], out)
        assert out.exists()

    def test_empty_rows_writes_header_only(self, tmp_path: Path) -> None:
        out = tmp_path / "empty.csv"
        write_generated_csv([], out)
        text = out.read_text(encoding=CSV_WRITE_ENCODING)
        lines = text.strip().splitlines()
        assert len(lines) == 1
        assert lines[0].split(",") == OUTPUT_COLUMNS


class TestWriteGeneratedCsvAuto:
    def test_uses_date_filter(self, tmp_path: Path) -> None:
        fixed = datetime(2026, 6, 1, 12, 0, 0, 999_000)
        path = write_generated_csv_auto(
            [_make_row()],
            subcategory="MLB",
            date_filter={"start": "2026-05-15", "end": "2026-06-01"},
            output_dir=tmp_path,
            now=fixed,
        )
        assert path.exists()
        assert path.name.endswith(".csv")
        assert "2026-05-15_to_2026-06-01" in path.name
        assert "MLB" in path.name


class TestDefaultOutputDir:
    def test_is_named_outputs_under_project_root(self) -> None:
        assert DEFAULT_OUTPUT_DIR.name == "outputs"
        assert DEFAULT_OUTPUT_DIR.is_absolute()


def test_build_path_default_output_dir_under_project() -> None:
    """Default path targets repo outputs/ (used when output_dir omitted)."""
    p = build_generated_csv_path(
        "X",
        "2026-01-01",
        "2026-01-02",
        now=datetime(2030, 1, 1, 0, 0, 0, 0),
    )
    assert "outputs" in p.parts
    assert p.name.startswith("generated_X_")
