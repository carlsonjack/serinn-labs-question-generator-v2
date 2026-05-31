"""Unit tests for F1 category normalizer."""

from __future__ import annotations

from pathlib import Path

from core.parsers.contracts import (
    DetectedFile,
    InputProfile,
    SourceRole,
)
from core.parsers.f1.normalizer import F1CategoryNormalizer


def test_f1_normalizer_filters_race_and_sets_display() -> None:
    fm = {
        "event_id": "event_id",
        "event_name": "event_name",
        "event_date": "event_date",
        "session_type": "session_type",
    }
    detected = DetectedFile(
        file_path=Path("dummy.xlsx"),
        format_name="xlsx",
        source_role=SourceRole.EVENT_SOURCE,
        sheet_name="F1 Schedule",
        header_row_index=0,
        columns=list(fm.values()),
        field_mappings=fm,
        confidence=1.0,
        records=[
            {
                "event_id": "F1000002",
                "event_name": "Australian Grand Prix - Race",
                "event_date": "2026-03-08 14:00:00",
                "session_type": "Race",
            },
            {
                "event_id": "F1000001",
                "event_name": "Australian Grand Prix - Qualifying",
                "event_date": "2026-03-08 12:00:00",
                "session_type": "Qualifying",
            },
        ],
        profile_used=InputProfile(
            profile_name="test",
            category_key="f1",
            file_pattern="*.xlsx",
            source_role=SourceRole.EVENT_SOURCE,
            format_name="xlsx",
            sheet_name="F1 Schedule",
            header_row_index=0,
            field_mappings=fm,
        ),
    )
    settings = {
        "date_filter": {"start": "2026-01-01", "end": "2026-12-31"},
        "inputs": {
            "packages": {
                "f1": {
                    "placeholder_home_team": "Driver_A",
                    "placeholder_away_team": "Driver_B",
                },
            },
        },
    }
    bundle = F1CategoryNormalizer().normalize([detected], settings)

    assert len(bundle.events) == 1
    ev = bundle.events[0]
    assert ev.event_id == "F1000002"
    assert ev.event_display == "Australian Grand Prix - Race"
    assert ev.subcategory == "F1"
    assert ev.home_team == "Driver_A"
    assert ev.away_team == "Driver_B"
    assert bundle.player_stats == []


def test_f1_normalizer_loads_driver_standings() -> None:
    event_fm = {
        "event_id": "event_id",
        "event_name": "event_name",
        "event_date": "event_date",
        "session_type": "session_type",
    }
    event_detected = DetectedFile(
        file_path=Path("schedule.xlsx"),
        format_name="xlsx",
        source_role=SourceRole.EVENT_SOURCE,
        sheet_name="F1 Schedule",
        header_row_index=0,
        columns=list(event_fm.values()),
        field_mappings=event_fm,
        confidence=1.0,
        records=[
            {
                "event_id": "F1000002",
                "event_name": "Monaco Grand Prix - Race",
                "event_date": "2026-06-08 14:00:00",
                "session_type": "Race",
            },
        ],
        profile_used=None,
    )
    metric_detected = DetectedFile(
        file_path=Path("standings.xlsx"),
        format_name="xlsx",
        source_role=SourceRole.METRIC_SOURCE,
        sheet_name="Standings",
        header_row_index=1,
        columns=["POS.", "DRIVER", "TEAM", "PTS"],
        field_mappings={"player_name": "DRIVER", "team": "TEAM"},
        confidence=1.0,
        records=[
            {"POS.": "1", "DRIVER": "Antonelli", "TEAM": "Mercedes", "PTS": "131"},
            {"POS.": "2", "DRIVER": "Russell", "TEAM": "Mercedes", "PTS": "88"},
        ],
        profile_used=None,
    )
    settings = {
        "date_filter": {"start": "2026-06-01", "end": "2026-06-30"},
        "inputs": {"packages": {"f1": {"competition_format": "field"}}},
    }
    bundle = F1CategoryNormalizer().normalize([event_detected, metric_detected], settings)

    assert len(bundle.events) == 1
    assert len(bundle.player_stats) == 2
    assert bundle.player_stats[0].player_name == "Antonelli"
    assert bundle.player_stats[0].source_team == "Mercedes"
    assert bundle.player_stats[0].stat_values.get("PTS") == 131.0
