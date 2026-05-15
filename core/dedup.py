"""Deduplication layer (EPIC 6, Task 6.1).

Identifies and removes exact-duplicate output rows and flags near-duplicates
for human review.  Exact duplicates are detected via a hash of
(subcategory, event, question).  Near-duplicates share the same event but have
similar (not identical) question text, measured by :class:`difflib.SequenceMatcher`.
"""

from __future__ import annotations

import csv
import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence

from core.csv_export import CSV_WRITE_ENCODING
from core.generation.row_assembler import OUTPUT_COLUMNS, OutputRow

logger = logging.getLogger(__name__)

DEFAULT_SIMILARITY_THRESHOLD: float = 0.85
"""Minimum SequenceMatcher ratio for two questions to be considered near-duplicates."""


def row_hash(row: OutputRow) -> str:
    """Compute a deterministic hash from ``(subcategory, event, question)``."""
    key = f"{row.subcategory}\x1f{row.event}\x1f{row.question}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _question_similarity(a: str, b: str) -> float:
    """Return a 0–1 similarity ratio between two question strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


@dataclass
class NearDuplicatePair:
    """Records a pair of rows flagged as near-duplicates."""

    row_a: OutputRow
    row_b: OutputRow
    similarity: float
    reason: str


@dataclass
class DeduplicationResult:
    """Outcome of running the full deduplication pass."""

    clean_rows: list[OutputRow] = field(default_factory=list)
    flagged_rows: list[OutputRow] = field(default_factory=list)
    flagged_pairs: list[NearDuplicatePair] = field(default_factory=list)
    exact_duplicates_removed: int = 0
    near_duplicates_flagged: int = 0

    @property
    def total_input(self) -> int:
        return (
            len(self.clean_rows)
            + self.exact_duplicates_removed
            + len(self.flagged_rows)
        )


def _remove_exact_duplicates(rows: Sequence[OutputRow]) -> tuple[list[OutputRow], int]:
    """Remove rows whose ``row_hash`` has already been seen.

    Returns the deduplicated list and the count of duplicates removed.
    First occurrence is always kept.
    """
    seen: set[str] = set()
    unique: list[OutputRow] = []
    removed = 0
    for row in rows:
        h = row_hash(row)
        if h in seen:
            removed += 1
            continue
        seen.add(h)
        unique.append(row)
    return unique, removed


def _find_near_duplicates(
    rows: Sequence[OutputRow],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[list[OutputRow], list[OutputRow], list[NearDuplicatePair]]:
    """Partition *rows* into clean and flagged based on question similarity.

    Rows sharing the same ``event`` value are compared pairwise.  When any
    pair exceeds *threshold*, **both** rows are moved to the flagged set
    (unless already flagged).  The first occurrence of a question is never
    flagged on its own — only when a later row is "too similar" to it.

    Returns ``(clean, flagged, pairs)``.
    """
    by_event: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        by_event[row.event].append(idx)

    flagged_indices: set[int] = set()
    pairs: list[NearDuplicatePair] = []

    for _event, indices in by_event.items():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                idx_a, idx_b = indices[i], indices[j]
                sim = _question_similarity(
                    rows[idx_a].question, rows[idx_b].question
                )
                if sim >= threshold:
                    pairs.append(
                        NearDuplicatePair(
                            row_a=rows[idx_a],
                            row_b=rows[idx_b],
                            similarity=round(sim, 4),
                            reason=(
                                f"Questions share event '{rows[idx_a].event}' "
                                f"with {sim:.1%} text similarity"
                            ),
                        )
                    )
                    flagged_indices.add(idx_a)
                    flagged_indices.add(idx_b)

    clean = [r for i, r in enumerate(rows) if i not in flagged_indices]
    flagged = [r for i, r in enumerate(rows) if i in flagged_indices]
    return clean, flagged, pairs


def deduplicate(
    rows: Sequence[OutputRow],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> DeduplicationResult:
    """Run the full deduplication pipeline on a list of output rows.

    1. Remove exact duplicates (identical subcategory + event + question).
    2. Flag near-duplicates (same event, similar question text) for review.

    Parameters
    ----------
    rows:
        Output rows to deduplicate.
    similarity_threshold:
        Minimum ratio (0–1) for two questions to be flagged as near-duplicates.
        Defaults to :data:`DEFAULT_SIMILARITY_THRESHOLD` (0.85).
    """
    after_exact, exact_removed = _remove_exact_duplicates(rows)
    if exact_removed:
        logger.info("Removed %d exact duplicate(s)", exact_removed)

    clean, flagged, pairs = _find_near_duplicates(
        after_exact, threshold=similarity_threshold
    )
    if flagged:
        logger.info(
            "Flagged %d row(s) as near-duplicate(s) (%d pair(s))",
            len(flagged),
            len(pairs),
        )

    return DeduplicationResult(
        clean_rows=clean,
        flagged_rows=flagged,
        flagged_pairs=pairs,
        exact_duplicates_removed=exact_removed,
        near_duplicates_flagged=len(flagged),
    )


def write_flagged_csv(
    flagged_rows: Sequence[OutputRow],
    pairs: Sequence[NearDuplicatePair],
    output_path: str | Path = "outputs/flagged.csv",
) -> Path:
    """Write near-duplicate rows to a CSV file for human review.

    The CSV contains the standard output columns plus ``similarity`` and
    ``reason`` columns to help reviewers understand why a row was flagged.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    pair_lookup: dict[str, NearDuplicatePair] = {}
    for pair in pairs:
        h_a = row_hash(pair.row_a)
        h_b = row_hash(pair.row_b)
        if h_a not in pair_lookup:
            pair_lookup[h_a] = pair
        if h_b not in pair_lookup:
            pair_lookup[h_b] = pair

    fieldnames = OUTPUT_COLUMNS + ["similarity", "reason"]

    with path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in flagged_rows:
            row_dict: dict[str, Any] = row.to_dict()
            pair = pair_lookup.get(row_hash(row))
            if pair:
                row_dict["similarity"] = str(pair.similarity)
                row_dict["reason"] = pair.reason
            else:
                row_dict["similarity"] = ""
                row_dict["reason"] = "near-duplicate (see paired row)"
            writer.writerow(row_dict)

    logger.info("Wrote %d flagged row(s) to %s", len(flagged_rows), path)
    return path
