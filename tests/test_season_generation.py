"""Season-scoped prompt item generation."""

from __future__ import annotations

from core.pipeline import build_prompt_items
from core.parsers.contracts import NormalizedBundle, NormalizedEvent, PlayerStatRecord
from core.template_config.schema import QuestionTemplate


def _event(eid: str, home: str, away: str) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=eid,
        subcategory="WNBA",
        home_team=home,
        away_team=away,
        event_datetime="2026-05-08T19:00:00",
    )


def _championship_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="WNBA-007",
        subcategory="WNBA",
        question_family="event",
        question="Who will win the WNBA Championship?",
        answer_type="multiple_choice",
        answer_options="{schedule_teams}",
        priority=1,
        requires_entities=False,
        generation_scope="season",
    )


def _game_winner_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="WNBA-001",
        subcategory="WNBA",
        question_family="event",
        question="Who will win {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{home_team}||{away_team}",
        priority=1,
        requires_entities=False,
    )


def _season_entity_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="WNBA-008",
        subcategory="WNBA",
        question_family="entity_stat",
        question="Who will lead the league in points?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority=1,
        requires_entities=True,
        stat_column="PTS",
        top_n_per_team=3,
        generation_scope="season",
    )


def _bundle(events: list[NormalizedEvent], players: list[PlayerStatRecord]) -> NormalizedBundle:
    return NormalizedBundle(
        events=events,
        player_stats=players,
        entities=[],
        issues=[],
    )


def test_season_championship_emits_one_item_with_all_teams():
    events = [
        _event("E1", "Seattle Storm", "Las Vegas Aces"),
        _event("E2", "Indiana Fever", "Chicago Sky"),
        _event("E3", "Chicago Sky", "Seattle Storm"),
    ]
    bundle = _bundle(events, [])
    settings = {"inputs": {"category_key": "wnba"}, "date_filter": {"end": "2026-09-27"}}
    items = build_prompt_items(bundle, [_championship_tpl()], settings)
    assert len(items) == 1
    assert items[0].event.event_display == "WNBA 2026 Season"
    assert items[0].schedule_teams == [
        "Chicago Sky",
        "Indiana Fever",
        "Las Vegas Aces",
        "Seattle Storm",
    ]


def test_per_event_template_still_emits_per_game():
    events = [
        _event("E1", "Seattle Storm", "Las Vegas Aces"),
        _event("E2", "Indiana Fever", "Chicago Sky"),
    ]
    bundle = _bundle(events, [])
    settings = {"inputs": {"category_key": "wnba"}}
    items = build_prompt_items(bundle, [_game_winner_tpl()], settings)
    assert len(items) == 2
    assert {i.event.event_id for i in items} == {"E1", "E2"}


def test_mixed_season_and_per_event_templates():
    events = [
        _event("E1", "Seattle Storm", "Las Vegas Aces"),
        _event("E2", "Indiana Fever", "Chicago Sky"),
    ]
    bundle = _bundle(events, [])
    settings = {"inputs": {"category_key": "wnba"}, "date_filter": {"end": "2026-09-27"}}
    items = build_prompt_items(bundle, [_championship_tpl(), _game_winner_tpl()], settings)
    assert len(items) == 3
    season_items = [i for i in items if i.template.id == "WNBA-007"]
    game_items = [i for i in items if i.template.id == "WNBA-001"]
    assert len(season_items) == 1
    assert len(game_items) == 2


def test_season_entity_stat_uses_league_wide_players():
    events = [_event("E1", "Seattle Storm", "Las Vegas Aces")]
    players = [
        PlayerStatRecord("Low Scorer", "IND", "IND", {"PTS": 5.0}, None, 1),
        PlayerStatRecord("Mid Scorer", "LV", "LV", {"PTS": 15.0}, None, 2),
        PlayerStatRecord("Top Scorer", "SEA", "SEA", {"PTS": 25.0}, None, 3),
        PlayerStatRecord("Second Top", "CHI", "CHI", {"PTS": 20.0}, None, 4),
    ]
    bundle = _bundle(events, players)
    settings = {"inputs": {"category_key": "wnba"}}
    items = build_prompt_items(bundle, [_season_entity_tpl()], settings)
    assert len(items) == 1
    names = [p.player_name for p in items[0].players]
    assert names == ["Top Scorer", "Second Top", "Mid Scorer"]
