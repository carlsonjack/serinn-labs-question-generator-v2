"""Team alias registry: loader integrity and per-league resolution."""

from __future__ import annotations

import pytest

from core.parsers.teams.registry import get_flat_map, list_registered_packages, reload_team_aliases
from core.parsers.team_lookup import resolve_stats_team_code


@pytest.fixture(autouse=True)
def _fresh_registry() -> None:
    reload_team_aliases()


def test_all_yaml_files_load_without_duplicate_aliases() -> None:
    packages = list_registered_packages()
    assert "mlb" in packages
    assert "wnba" in packages
    assert "mls" in packages
    assert "laliga" in packages
    assert "ncaaf" in packages
    assert "ncaab" in packages


@pytest.mark.parametrize(
    ("package", "label", "expected"),
    [
        ("mlb", "Houston Astros", "HOU"),
        ("mlb", "Astros", "HOU"),
        ("mlb", "Los Angeles Dodgers", "LAD"),
        ("mlb", "Angels", "LAA"),
        ("wnba", "Los Angeles Sparks", "LA"),
        ("wnba", "Las Vegas Aces", "LV"),
        ("mls", "Los Angeles FC", "LAFC"),
        ("mls", "LA Galaxy", "LAG"),
        ("mls", "Galaxy", "LAG"),
        ("nba", "Los Angeles Lakers", "LAL"),
        ("nba", "Los Angeles Clippers", "LAC"),
        ("nfl", "Los Angeles Rams", "LAR"),
        ("nfl", "Los Angeles Chargers", "LAC"),
        ("nhl", "Los Angeles Kings", "LAK"),
        ("laliga", "Real Madrid", "RMA"),
        ("laliga", "Barcelona", "BAR"),
        ("ncaaf", "Alabama", "Alabama"),
        ("ncaaf", "USC", "USC"),
        ("ncaaf", "Southern California", "USC"),
        ("ncaab", "Duke", "Duke"),
        ("ncaab", "UConn", "Connecticut"),
    ],
)
def test_resolve_stats_team_code(package: str, label: str, expected: str) -> None:
    assert resolve_stats_team_code(label, package) == expected


def test_package_key_normalization_case_and_spacing() -> None:
    assert resolve_stats_team_code("Lakers", "NBA") == "LAL"
    assert resolve_stats_team_code("Lakers", "nba") == "LAL"
    assert resolve_stats_team_code("Real Madrid", "La Liga") == "RMA"
    assert resolve_stats_team_code("Real Madrid", "laliga") == "RMA"


def test_unknown_package_returns_label_unchanged() -> None:
    assert resolve_stats_team_code("Some Club", "soccer") == "Some Club"


def test_get_flat_map_mlb_matches_legacy_shape() -> None:
    mlb = get_flat_map("mlb")
    assert mlb is not None
    assert mlb["Houston Astros"] == "HOU"
    assert mlb["HOU"] == "HOU"


def test_college_does_not_map_ambiguous_tigers() -> None:
    assert resolve_stats_team_code("Tigers", "ncaaf") == "Tigers"
    assert resolve_stats_team_code("Wildcats", "ncaab") == "Wildcats"
