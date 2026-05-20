"""WNBA schedule name ↔ stats TEAM code mapping."""

from __future__ import annotations

from core.parsers.contracts import PlayerStatRecord
from core.parsers.team_lookup import resolve_stats_team_code
from core.pipeline import top_players_for_team


def test_resolve_stats_team_code_wnba_full_names():
    assert resolve_stats_team_code("Las Vegas Aces", "wnba") == "LV"
    assert resolve_stats_team_code("Golden State Valkyries", "wnba") == "GS"
    assert resolve_stats_team_code("Seattle Storm", "wnba") == "SEA"
    assert resolve_stats_team_code("Los Angeles Sparks", "wnba") == "LA"


def test_resolve_stats_team_code_wnba_abbrev_passthrough():
    assert resolve_stats_team_code("LV", "wnba") == "LV"
    assert resolve_stats_team_code("GS", "wnba") == "GS"


def test_resolve_stats_team_code_unknown_package_unchanged():
    assert resolve_stats_team_code("Golden State Valkyries", "soccer") == "Golden State Valkyries"


def test_top_players_for_team_wnba_matches_stats_team_column():
    stats = [
        PlayerStatRecord(
            player_name="A'ja Wilson",
            team="LV",
            source_team="LV",
            stat_values={"PTS": 22.0},
            source_sheet=None,
            row_number=1,
        ),
        PlayerStatRecord(
            player_name="Other",
            team="GS",
            source_team="GS",
            stat_values={"PTS": 30.0},
            source_sheet=None,
            row_number=2,
        ),
    ]
    found = top_players_for_team(stats, "Las Vegas Aces", "PTS", 2, category_key="wnba")
    assert [p.player_name for p in found] == ["A'ja Wilson"]
