"""Tests for spreadsheet column → stat_values key normalization."""

from __future__ import annotations

import pytest

from core.parsers.stat_keys import stat_storage_key


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("PTS", "PTS"),
        ("Goal Probability", "GOAL_PROBABILITY"),
        ("FG%", "FG%"),
        ("3P%", "3P%"),
        ("HR", "HR"),
        ("3PM", "3PM"),
    ],
)
def test_stat_storage_key(column: str, expected: str) -> None:
    assert stat_storage_key(column) == expected
