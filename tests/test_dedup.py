"""Tests for core.dedup (EPIC 6, Task 6.1)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.dedup import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DeduplicationResult,
    NearDuplicatePair,
    _find_near_duplicates,
    _question_similarity,
    _remove_exact_duplicates,
    deduplicate,
    row_hash,
    write_flagged_csv,
)
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    *,
    subcategory: str = "MLB",
    event: str = "Mets vs Yankees",
    question: str = "Who will win?",
    answer_type: str = "multiple_choice",
    answer_options: str = "Mets||Yankees",
    start_date: str = "2026-05-14T19:10:00",
    expiration_date: str = "2026-05-15T19:10:00",
    resolution_date: str = "2026-05-15T23:10:00",
    priority: int | str = 1,
    topic_import_id: str = "mlb-regular-season",
) -> OutputRow:
    return OutputRow(
        topic_import_id=topic_import_id,
        subcategory=subcategory,
        event=event,
        question=question,
        answer_type=answer_type,
        answer_options=answer_options,
        start_date=start_date,
        expiration_date=expiration_date,
        resolution_date=resolution_date,
        priority=priority,
    )


# ===================================================================
# TestRowHash
# ===================================================================

class TestRowHash:
    """row_hash produces deterministic, collision-resistant digests."""

    def test_deterministic(self):
        row = _make_row()
        assert row_hash(row) == row_hash(row)

    def test_same_key_fields_same_hash(self):
        a = _make_row(start_date="2026-01-01T00:00:00")
        b = _make_row(start_date="2026-01-01T00:00:00")
        assert row_hash(a) == row_hash(b)

    def test_different_start_date_different_hash(self):
        a = _make_row(start_date="2026-01-01T00:00:00")
        b = _make_row(start_date="2099-12-31T23:59:59")
        assert row_hash(a) != row_hash(b)

    def test_different_subcategory_different_hash(self):
        a = _make_row(subcategory="MLB")
        b = _make_row(subcategory="NBA")
        assert row_hash(a) != row_hash(b)

    def test_different_event_different_hash(self):
        a = _make_row(event="Mets vs Yankees")
        b = _make_row(event="Dodgers vs Giants")
        assert row_hash(a) != row_hash(b)

    def test_different_question_different_hash(self):
        a = _make_row(question="Who will win?")
        b = _make_row(question="Will total runs exceed 8.5?")
        assert row_hash(a) != row_hash(b)

    def test_hash_is_hex_string(self):
        h = row_hash(_make_row())
        assert isinstance(h, str)
        int(h, 16)  # valid hex

    def test_hash_length(self):
        assert len(row_hash(_make_row())) == 64  # SHA-256


# ===================================================================
# TestQuestionSimilarity
# ===================================================================

class TestQuestionSimilarity:
    """_question_similarity returns sensible 0–1 ratios."""

    def test_identical(self):
        assert _question_similarity("Who will win?", "Who will win?") == 1.0

    def test_case_insensitive(self):
        assert _question_similarity("Who Will Win?", "who will win?") == 1.0

    def test_completely_different(self):
        ratio = _question_similarity("Who will win?", "Total runs over 8.5?")
        assert ratio < 0.5

    def test_similar_strings(self):
        ratio = _question_similarity(
            "Who will win Mets vs Yankees?",
            "Who will win Mets vs Dodgers?",
        )
        assert 0.7 < ratio < 1.0


# ===================================================================
# TestRemoveExactDuplicates
# ===================================================================

class TestRemoveExactDuplicates:
    """_remove_exact_duplicates keeps first occurrence only."""

    def test_no_duplicates(self):
        rows = [_make_row(question="Q1"), _make_row(question="Q2")]
        unique, removed = _remove_exact_duplicates(rows)
        assert len(unique) == 2
        assert removed == 0

    def test_exact_duplicate_removed(self):
        row = _make_row()
        rows = [row, _make_row()]  # identical fields
        unique, removed = _remove_exact_duplicates(rows)
        assert len(unique) == 1
        assert removed == 1

    def test_three_copies(self):
        rows = [_make_row(), _make_row(), _make_row()]
        unique, removed = _remove_exact_duplicates(rows)
        assert len(unique) == 1
        assert removed == 2

    def test_empty_input(self):
        unique, removed = _remove_exact_duplicates([])
        assert unique == []
        assert removed == 0

    def test_preserves_order(self):
        rows = [
            _make_row(question="First"),
            _make_row(question="Second"),
            _make_row(question="First"),  # duplicate of first
        ]
        unique, removed = _remove_exact_duplicates(rows)
        assert [r.question for r in unique] == ["First", "Second"]
        assert removed == 1

    def test_non_key_field_difference_still_duplicate(self):
        """Rows differing only in non-key fields (e.g. priority) are still exact dupes."""
        a = _make_row(priority=1)
        b = _make_row(priority="")
        unique, removed = _remove_exact_duplicates([a, b])
        assert len(unique) == 1
        assert removed == 1

    def test_same_matchup_different_start_date_not_duplicate(self):
        rows = [
            _make_row(start_date="2026-05-18T19:10:00"),
            _make_row(start_date="2026-05-19T19:10:00"),
        ]
        unique, removed = _remove_exact_duplicates(rows)
        assert len(unique) == 2
        assert removed == 0


# ===================================================================
# TestFindNearDuplicates
# ===================================================================

class TestFindNearDuplicates:
    """_find_near_duplicates flags rows with similar questions sharing an event."""

    def test_no_near_duplicates(self):
        rows = [
            _make_row(question="Who will win?"),
            _make_row(question="Will total runs exceed 8.5?"),
        ]
        clean, flagged, pairs = _find_near_duplicates(rows, threshold=0.85)
        assert len(clean) == 2
        assert len(flagged) == 0
        assert len(pairs) == 0

    def test_near_duplicate_flagged(self):
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees tonight?"),
        ]
        clean, flagged, pairs = _find_near_duplicates(rows, threshold=0.80)
        assert len(flagged) == 2
        assert len(pairs) == 1
        assert len(clean) == 0

    def test_different_events_not_compared(self):
        """Rows with different events are never flagged as near-duplicates."""
        rows = [
            _make_row(event="Mets vs Yankees", question="Who will win?"),
            _make_row(event="Dodgers vs Giants", question="Who will win?"),
        ]
        clean, flagged, pairs = _find_near_duplicates(rows, threshold=0.80)
        assert len(clean) == 2
        assert len(flagged) == 0

    def test_threshold_boundary(self):
        """At threshold=1.0, only perfectly identical questions are flagged."""
        rows = [
            _make_row(question="Who will win?"),
            _make_row(question="Who will win!"),  # different punctuation
        ]
        clean, flagged, _pairs = _find_near_duplicates(rows, threshold=1.0)
        assert len(flagged) == 0
        assert len(clean) == 2

    def test_pair_records_similarity(self):
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees tonight?"),
        ]
        _clean, _flagged, pairs = _find_near_duplicates(rows, threshold=0.70)
        assert len(pairs) == 1
        assert 0.7 <= pairs[0].similarity <= 1.0

    def test_multiple_near_dupes_in_same_event(self):
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees tonight?"),
            _make_row(question="Who will win Mets vs Yankees today?"),
        ]
        _clean, flagged, pairs = _find_near_duplicates(rows, threshold=0.70)
        assert len(flagged) == 3
        assert len(pairs) >= 2  # at least 2 similar pairs


# ===================================================================
# TestDeduplicate (integration of both passes)
# ===================================================================

class TestDeduplicate:
    """deduplicate() runs exact dedup; near-duplicate flagging is currently disabled."""

    def test_empty_input(self):
        result = deduplicate([])
        assert result.clean_rows == []
        assert result.flagged_rows == []
        assert result.exact_duplicates_removed == 0
        assert result.near_duplicates_flagged == 0

    def test_no_duplicates(self):
        rows = [_make_row(question="Q1"), _make_row(question="Q2")]
        result = deduplicate(rows)
        assert len(result.clean_rows) == 2
        assert result.exact_duplicates_removed == 0
        assert result.near_duplicates_flagged == 0

    def test_exact_only(self):
        rows = [_make_row(), _make_row()]
        result = deduplicate(rows)
        assert len(result.clean_rows) == 1
        assert result.exact_duplicates_removed == 1
        assert result.near_duplicates_flagged == 0

    def test_near_only(self):
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees tonight?"),
        ]
        result = deduplicate(rows, similarity_threshold=0.80)
        assert len(result.clean_rows) == 2
        assert len(result.flagged_rows) == 0
        assert result.exact_duplicates_removed == 0
        assert result.near_duplicates_flagged == 0

    def test_exact_then_near(self):
        """Exact dedup runs first; near-dup flagging disabled so similar rows stay in clean."""
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees?"),  # exact dupe
            _make_row(question="Who will win Mets vs Yankees tonight?"),  # near dupe
        ]
        result = deduplicate(rows, similarity_threshold=0.80)
        assert result.exact_duplicates_removed == 1
        assert result.near_duplicates_flagged == 0
        assert len(result.clean_rows) == 2

    def test_total_input_property(self):
        rows = [
            _make_row(question="Q1"),
            _make_row(question="Q1"),  # exact dupe
            _make_row(question="Q2"),
        ]
        result = deduplicate(rows)
        assert result.total_input == 3

    def test_custom_threshold(self):
        rows = [
            _make_row(question="Who will win?"),
            _make_row(question="Who will win tonight?"),
        ]
        strict = deduplicate(rows, similarity_threshold=0.99)
        assert len(strict.flagged_rows) == 0
        assert len(strict.clean_rows) == 2
        loose = deduplicate(rows, similarity_threshold=0.50)
        assert len(loose.flagged_rows) == 0
        assert len(loose.clean_rows) == 2

    def test_clean_rows_exclude_flagged(self):
        rows = [
            _make_row(question="Who will win Mets vs Yankees?"),
            _make_row(question="Who will win Mets vs Yankees tonight?"),
            _make_row(question="Will total runs exceed 8.5?"),
        ]
        result = deduplicate(rows, similarity_threshold=0.80)
        clean_questions = {r.question for r in result.clean_rows}
        flagged_questions = {r.question for r in result.flagged_rows}
        assert len(flagged_questions) == 0
        assert len(clean_questions) == 3
        assert clean_questions & flagged_questions == set()


# ===================================================================
# TestDeduplicationResult
# ===================================================================

class TestDeduplicationResult:
    """DeduplicationResult dataclass and property."""

    def test_defaults(self):
        r = DeduplicationResult()
        assert r.clean_rows == []
        assert r.flagged_rows == []
        assert r.flagged_pairs == []
        assert r.exact_duplicates_removed == 0
        assert r.near_duplicates_flagged == 0

    def test_total_input(self):
        r = DeduplicationResult(
            clean_rows=[_make_row(question="A")],
            flagged_rows=[_make_row(question="B"), _make_row(question="C")],
            exact_duplicates_removed=3,
        )
        assert r.total_input == 6  # 1 clean + 3 removed + 2 flagged


# ===================================================================
# TestWriteFlaggedCsv
# ===================================================================

class TestWriteFlaggedCsv:
    """write_flagged_csv writes a well-formed CSV for review."""

    def test_creates_file(self, tmp_path: Path):
        row_a = _make_row(question="Who will win Mets vs Yankees?")
        row_b = _make_row(question="Who will win Mets vs Yankees tonight?")
        pair = NearDuplicatePair(
            row_a=row_a,
            row_b=row_b,
            similarity=0.92,
            reason="test reason",
        )
        out = tmp_path / "flagged.csv"
        result = write_flagged_csv([row_a, row_b], [pair], output_path=out)
        assert result == out
        assert out.exists()

    def test_csv_columns(self, tmp_path: Path):
        row = _make_row()
        pair = NearDuplicatePair(
            row_a=row, row_b=row, similarity=1.0, reason="self"
        )
        out = tmp_path / "flagged.csv"
        write_flagged_csv([row], [pair], output_path=out)

        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == OUTPUT_COLUMNS + ["similarity", "reason"]

    def test_csv_row_count(self, tmp_path: Path):
        rows = [_make_row(question=f"Q{i}") for i in range(3)]
        pair = NearDuplicatePair(
            row_a=rows[0], row_b=rows[1], similarity=0.88, reason="similar"
        )
        out = tmp_path / "flagged.csv"
        write_flagged_csv(rows, [pair], output_path=out)

        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            data = list(csv.DictReader(fh))
        assert len(data) == 3

    def test_csv_contains_similarity_and_reason(self, tmp_path: Path):
        row_a = _make_row(question="Q1")
        row_b = _make_row(question="Q2")
        pair = NearDuplicatePair(
            row_a=row_a, row_b=row_b, similarity=0.91, reason="test reason"
        )
        out = tmp_path / "flagged.csv"
        write_flagged_csv([row_a, row_b], [pair], output_path=out)

        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            data = list(csv.DictReader(fh))
        assert data[0]["similarity"] == "0.91"
        assert data[0]["reason"] == "test reason"

    def test_empty_flagged_creates_header_only(self, tmp_path: Path):
        out = tmp_path / "flagged.csv"
        write_flagged_csv([], [], output_path=out)

        with out.open(encoding=CSV_WRITE_ENCODING) as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == OUTPUT_COLUMNS + ["similarity", "reason"]
            assert list(reader) == []

    def test_creates_parent_directories(self, tmp_path: Path):
        out = tmp_path / "nested" / "dir" / "flagged.csv"
        write_flagged_csv([], [], output_path=out)
        assert out.exists()


# ===================================================================
# TestDefaultThreshold
# ===================================================================

class TestDefaultThreshold:
    """DEFAULT_SIMILARITY_THRESHOLD is a sensible value."""

    def test_value(self):
        assert DEFAULT_SIMILARITY_THRESHOLD == 0.85

    def test_between_zero_and_one(self):
        assert 0.0 < DEFAULT_SIMILARITY_THRESHOLD < 1.0
