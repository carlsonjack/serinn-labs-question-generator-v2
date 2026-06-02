"""Golf category normalizer and field entity-stat pipeline tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.generation.event_fill import fill_sports_template_text
from core.parsers.ai_profile_builder import propose_normalization_spec
from core.parsers.contracts import (
    DetectedFile,
    InputProfile,
    NormalizationSpec,
    SourceNormalizationSpec,
    SourceRole,
    ValidationSeverity,
)
from core.parsers.declarative import execute_normalization_spec, validate_normalization_spec
from core.parsers.golf.normalizer import GolfCategoryNormalizer
from core.pipeline import build_prompt_items, top_players_for_field
from core.template_config.schema import QuestionTemplate


def _golf_settings() -> dict:
    return {
        "date_filter": {"start": "2026-01-01", "end": "2026-12-31"},
        "inputs": {
            "category_key": "golf",
            "packages": {
                "golf": {
                    "competition_format": "field",
                    "placeholder_home_team": "Golfer_A",
                    "placeholder_away_team": "Golfer_B",
                    "field_team_code": "FIELD",
                    "ascending_stat_columns": ["RANK", "FedExCup Rank"],
                    "skip_status_values": ["complete", "cancelled", "canceled"],
                }
            },
        },
    }


def _write_golf_schedule(path: Path) -> None:
    rows = [
        {
            "start_date": "2026-03-05",
            "season": 2026,
            "tour": "pga",
            "event_name": "Arnold Palmer Invitational",
            "country": "USA",
            "course": "Bay Hill Club",
            "status": "scheduled",
            "winner": "",
        },
        {
            "start_date": "2026-01-08",
            "season": 2026,
            "tour": "pga",
            "event_name": "The Sentry [ CANCELLED ]",
            "country": "USA",
            "course": "Plantation Course",
            "status": "complete",
            "winner": "",
        },
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="pga_2026_schedule", index=False)


def _write_golf_rankings(path: Path) -> None:
    rows = [
        {
            "RANK": 1,
            "MOVEMENT": 0,
            "PLAYER_ID": 1,
            "PLAYER": "Scottie Scheffler",
            "AVG POINTS": 16.4,
            "TOTAL POINTS": 672.0,
        },
        {
            "RANK": 2,
            "MOVEMENT": 0,
            "PLAYER_ID": 2,
            "PLAYER": "Rory McIlroy",
            "AVG POINTS": 9.9,
            "TOTAL POINTS": 447.0,
        },
        {
            "RANK": 3,
            "MOVEMENT": 0,
            "PLAYER_ID": 3,
            "PLAYER": "Jon Rahm",
            "AVG POINTS": 8.5,
            "TOTAL POINTS": 400.0,
        },
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="World Rankings", index=False)


def _schedule_detected(path: Path) -> DetectedFile:
    fm = {
        "event_date": "start_date",
        "event_name": "event_name",
        "event_display": "event_name",
        "status": "status",
    }
    df = pd.read_excel(path)
    return DetectedFile(
        file_path=path,
        format_name="xlsx",
        source_role=SourceRole.EVENT_SOURCE,
        sheet_name="pga_2026_schedule",
        header_row_index=0,
        columns=list(df.columns),
        field_mappings=fm,
        confidence=1.0,
        records=df.to_dict(orient="records"),
        profile_used=InputProfile(
            profile_name="test",
            category_key="golf",
            file_pattern="*.xlsx",
            source_role=SourceRole.EVENT_SOURCE,
            format_name="xlsx",
            sheet_name="pga_2026_schedule",
            header_row_index=0,
            field_mappings=fm,
        ),
    )


def _rankings_detected(path: Path) -> DetectedFile:
    fm = {"player_name": "PLAYER"}
    df = pd.read_excel(path)
    return DetectedFile(
        file_path=path,
        format_name="xlsx",
        source_role=SourceRole.METRIC_SOURCE,
        sheet_name="World Rankings",
        header_row_index=0,
        columns=list(df.columns),
        field_mappings=fm,
        confidence=1.0,
        records=df.to_dict(orient="records"),
        profile_used=InputProfile(
            profile_name="test",
            category_key="golf",
            file_pattern="*.xlsx",
            source_role=SourceRole.METRIC_SOURCE,
            format_name="xlsx",
            sheet_name="World Rankings",
            header_row_index=0,
            field_mappings=fm,
        ),
    )


def test_golf_normalizer_schedule_and_rankings(tmp_path: Path) -> None:
    sched = tmp_path / "schedule.xlsx"
    stats = tmp_path / "stats.xlsx"
    _write_golf_schedule(sched)
    _write_golf_rankings(stats)

    bundle = GolfCategoryNormalizer().normalize(
        [_schedule_detected(sched), _rankings_detected(stats)],
        _golf_settings(),
    )
    errors = [i for i in bundle.issues if i.severity == ValidationSeverity.ERROR]
    assert not errors
    assert len(bundle.events) == 1
    assert bundle.events[0].event_display == "Arnold Palmer Invitational"
    assert bundle.events[0].home_team == "Golfer_A"
    assert len(bundle.player_stats) == 3
    assert all(p.team == "FIELD" for p in bundle.player_stats)
    assert bundle.player_stats[0].stat_values["AVG_POINTS"] == 16.4


def test_field_declarative_spec_validates_without_teams() -> None:
    spec = NormalizationSpec(
        package_key="golf",
        competition_format="field",
        sources={
            "event_source": SourceNormalizationSpec(
                source_role=SourceRole.EVENT_SOURCE,
                file_pattern="schedule.xlsx",
                field_mappings={
                    "event_date": "start_date",
                    "event_name": "event_name",
                },
                metadata_mappings={"status": "status"},
            ),
            "metric_source": SourceNormalizationSpec(
                source_role=SourceRole.METRIC_SOURCE,
                file_pattern="stats.xlsx",
                field_mappings={"player_name": "PLAYER"},
                metric_mappings={"RANK": "RANK"},
            ),
        },
    )
    errors = [i for i in validate_normalization_spec(spec) if i.severity == ValidationSeverity.ERROR]
    assert not errors


def test_top_players_for_field_rank_vs_avg_points() -> None:
    from core.parsers.contracts import PlayerStatRecord

    stats = [
        PlayerStatRecord(
            player_name="Scottie Scheffler",
            team="FIELD",
            source_team="FIELD",
            stat_values={"RANK": 2.0, "AVG_POINTS": 16.4},
            source_sheet=None,
            row_number=1,
        ),
        PlayerStatRecord(
            player_name="Rory McIlroy",
            team="FIELD",
            source_team="FIELD",
            stat_values={"RANK": 1.0, "AVG_POINTS": 9.9},
            source_sheet=None,
            row_number=2,
        ),
    ]
    settings = _golf_settings()
    by_rank = [p.player_name for p in top_players_for_field(stats, "RANK", 2, category_key="golf", settings=settings)]
    by_avg = [p.player_name for p in top_players_for_field(stats, "AVG POINTS", 2, category_key="golf", settings=settings)]
    assert by_rank == ["Rory McIlroy", "Scottie Scheffler"]
    assert by_avg == ["Scottie Scheffler", "Rory McIlroy"]


def test_top_players_for_field_fedexcup_rank_ascending() -> None:
    from core.parsers.contracts import PlayerStatRecord
    from core.parsers.stat_keys import stat_storage_key

    stats = [
        PlayerStatRecord(
            player_name="Ludvig Aberg",
            team="FIELD",
            source_team="FIELD",
            stat_values={stat_storage_key("FedExCup Rank"): 1.0},
            source_sheet=None,
            row_number=1,
        ),
        PlayerStatRecord(
            player_name="Adrien Saddier",
            team="FIELD",
            source_team="FIELD",
            stat_values={stat_storage_key("FedExCup Rank"): 173.0},
            source_sheet=None,
            row_number=2,
        ),
        PlayerStatRecord(
            player_name="Akshay Bhatia",
            team="FIELD",
            source_team="FIELD",
            stat_values={stat_storage_key("FedExCup Rank"): 2.0},
            source_sheet=None,
            row_number=3,
        ),
    ]
    settings = _golf_settings()
    top = [
        p.player_name
        for p in top_players_for_field(
            stats, "FedExCup Rank", 2, category_key="golf", settings=settings
        )
    ]
    assert top == ["Ludvig Aberg", "Akshay Bhatia"]
    assert "Adrien Saddier" not in top


def test_golf_h2h_schedule_reads_teams_and_event_ids() -> None:
    fm = {
        "event_id": "event_id",
        "event_date": "event_date",
        "event_name": "event_name",
        "event_display": "event_name",
        "home_team": "home_team",
        "away_team": "away_team",
    }
    detected = DetectedFile(
        file_path=Path("h2h.xlsx"),
        format_name="xlsx",
        source_role=SourceRole.EVENT_SOURCE,
        sheet_name="Sheet1",
        header_row_index=0,
        columns=list(fm.values()),
        field_mappings=fm,
        confidence=1.0,
        records=[
            {
                "event_id": "pga-memorial-2026-m01",
                "event_name": "Memorial Tournament 2026",
                "event_date": "2026-06-04",
                "home_team": "1. S. Scheffler",
                "away_team": "2. Cam. Young",
            },
            {
                "event_id": "pga-memorial-2026-m02",
                "event_name": "Memorial Tournament 2026",
                "event_date": "2026-06-04",
                "home_team": "3. M. Fitzpatrick",
                "away_team": "5. S.W. Kim",
            },
            {
                "event_id": "pga-single-tournament",
                "event_name": "Arnold Palmer Invitational",
                "event_date": "2026-03-05",
                "home_team": "",
                "away_team": "",
            },
        ],
        profile_used=None,
    )
    bundle = GolfCategoryNormalizer().normalize([detected], _golf_settings())
    assert len(bundle.events) == 3
    assert bundle.events[0].event_id == "pga-memorial-2026-m01"
    assert bundle.events[0].home_team == "1. S. Scheffler"
    assert bundle.events[0].away_team == "2. Cam. Young"
    assert bundle.events[1].event_id == "pga-memorial-2026-m02"
    assert bundle.events[2].home_team == "Golfer_A"
    assert bundle.events[2].away_team == "Golfer_B"


def test_build_prompt_items_field_entity_stat(tmp_path: Path) -> None:
    sched = tmp_path / "schedule.xlsx"
    stats = tmp_path / "stats.xlsx"
    _write_golf_schedule(sched)
    _write_golf_rankings(stats)
    bundle = GolfCategoryNormalizer().normalize(
        [_schedule_detected(sched), _rankings_detected(stats)],
        _golf_settings(),
    )
    tpl = QuestionTemplate(
        id="golf_top",
        subcategory="Golf",
        question_family="entity_stat",
        question="Best at {event_name}?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority=1,
        requires_entities=True,
        stat_column="AVG POINTS",
        top_n_per_team=2,
    )
    settings = _golf_settings()
    items = build_prompt_items(bundle, [tpl], settings)
    assert len(items) == 1
    assert len(items[0].players) == 2
    assert items[0].players[0].player_name == "Scottie Scheffler"


def test_event_name_placeholder() -> None:
    from core.parsers.contracts import NormalizedEvent

    tpl = QuestionTemplate(
        id="t",
        subcategory="Golf",
        question_family="event",
        question="Who wins {event_name}?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority=1,
        requires_entities=False,
    )
    event = NormalizedEvent(
        event_id="e1",
        home_team="A",
        away_team="B",
        event_datetime="2026-03-05T00:00:00",
        subcategory="Golf",
        event_display="Arnold Palmer Invitational",
    )
    assert fill_sports_template_text(tpl.question, event, tpl) == (
        "Who wins Arnold Palmer Invitational?"
    )


def test_heuristic_golf_profile_proposal(tmp_path: Path) -> None:
    sched = tmp_path / "schedule.xlsx"
    stats = tmp_path / "stats.xlsx"
    _write_golf_schedule(sched)
    _write_golf_rankings(stats)
    spec, _ = propose_normalization_spec(
        _golf_settings(),
        category_key="golf",
        input_dir=tmp_path,
        file_config={"event_source": "schedule.xlsx", "metric_source": "stats.xlsx"},
        use_ai=False,
    )
    assert spec.competition_format == "field"
    errors = [i for i in validate_normalization_spec(spec) if i.severity == ValidationSeverity.ERROR]
    assert not errors
