"""Compose MLB source files into one normalized bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ..base import CategoryNormalizer
from ..contracts import DetectedFile, NormalizedBundle, SourceRole
from ..registry import register_category_normalizer
from ..validators import validate_date_filter_results, validate_schedule_teams_have_stats
from .schedule import MlbScheduleParser
from .stats import MlbStatsParser


def _category_key_from_detected_files(
    detected_files: Sequence[DetectedFile], *, default: str = "mlb"
) -> str:
    """Reuse the category key from detection (e.g. ``mls``) when re-parsing in normalize()."""

    for d in detected_files:
        prof = d.profile_used
        if prof is not None:
            raw = str(getattr(prof, "category_key", "") or "").strip()
            if raw:
                return raw
    return default


@register_category_normalizer("mlb")
class MlbCategoryNormalizer(CategoryNormalizer):
    """Normalize MLB schedule and stats sources into one bundle."""

    def normalize(
        self,
        detected_files: Sequence[DetectedFile],
        settings: Mapping[str, Any],
    ) -> NormalizedBundle:
        paths_by_role = {detected.source_role: detected.file_path for detected in detected_files}

        schedule_path = paths_by_role.get(SourceRole.EVENT_SOURCE)
        stats_path = paths_by_role.get(SourceRole.METRIC_SOURCE)
        if schedule_path is None:
            raise ValueError("MLB normalization requires an event source (schedule).")

        category_key = _category_key_from_detected_files(detected_files, default="mlb")
        schedule_result = (
            MlbScheduleParser(dict(settings), category_key=category_key)
            .load(schedule_path)
            .normalize()
        )

        issues = [
            *schedule_result.warnings,
            *schedule_result.errors,
        ]
        events = list(schedule_result.data)
        player_stats: list = []
        profiles = [
            profile
            for profile in (schedule_result.profile_used,)
            if profile is not None
        ]

        if stats_path is not None:
            stats_parser = MlbStatsParser(category_key=category_key).load(stats_path)
            stats_result = stats_parser.normalize()
            issues.extend(stats_result.warnings)
            issues.extend(stats_result.errors)
            player_stats = list(stats_result.data)
            if stats_result.profile_used is not None:
                profiles.append(stats_result.profile_used)

        issues.extend(validate_date_filter_results(events))
        issues.extend(
            validate_schedule_teams_have_stats(
                events,
                player_stats,
                category_key=category_key,
            )
        )
        return NormalizedBundle(
            events=events,
            player_stats=player_stats,
            issues=issues,
            profiles=profiles,
        )


def detect_mlb_inputs(input_dir: str | Path) -> list[Path]:
    """Return the default MLB sample inputs from a directory."""

    root = Path(input_dir)
    return [root / "schedule.xlsx", root / "stats.xlsx"]

