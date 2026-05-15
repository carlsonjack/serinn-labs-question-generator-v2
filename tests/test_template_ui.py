"""Template UI metadata."""

from __future__ import annotations

from core.template_config.schema import QuestionTemplate
from core.template_ui import (
    explain_template,
    filter_templates_for_package,
    humanize_package_key,
    infer_subcategory_for_package,
    package_aliases_for_settings,
    template_to_ui_dict,
)


def _event_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="t1",
        subcategory="MLB",
        question_family="event",
        question="Who wins {home_team} vs {away_team}?",
        answer_type="multiple_choice",
        answer_options="{home_team}||{away_team}",
        priority=1,
        requires_entities=False,
    )


def _entity_tpl() -> QuestionTemplate:
    return QuestionTemplate(
        id="t2",
        subcategory="MLB",
        question_family="entity_stat",
        question="Who hits a HR?",
        answer_type="multiple_choice",
        answer_options="{entity_options}",
        priority="",
        requires_entities=True,
        stat_column="HR",
        top_n_per_team=2,
    )


def test_template_to_ui_dict_has_explainer():
    d = template_to_ui_dict(_event_tpl(), enabled=True)
    assert d["id"] == "t1"
    assert "Who wins" in d["preview_question"]
    assert d["explainer"]
    assert isinstance(d["explainer"], list)


def test_entity_explainer_mentions_stat():
    lines = explain_template(_entity_tpl())
    assert any("HR" in line for line in lines)


def test_filter_templates_for_package_normalizes_case():
    templates = [_event_tpl(), _entity_tpl()]
    out = filter_templates_for_package(templates, "mlb")
    assert [t.id for t in out] == ["t1", "t2"]


def test_infer_subcategory_for_package_prefers_template_value():
    subcategory = infer_subcategory_for_package([_event_tpl()], "mlb")
    assert subcategory == "MLB"


def test_infer_subcategory_for_package_majority_not_first_by_id():
    """Avoid using sorted-by-id first template when many templates share one subcategory."""

    music = QuestionTemplate(
        id="music-mc-01",
        subcategory="Music",
        question_family="event",
        question="Q?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
    )
    movie_like = [
        QuestionTemplate(
            id=f"movie-yn-{i:02d}",
            subcategory="Movies",
            question_family="event",
            question="Q?",
            answer_type="yes_no",
            answer_options="Yes||No",
            priority="",
            requires_entities=False,
        )
        for i in range(9)
    ]
    # Both Music and Movies labels match this package (broad aliases).
    aliases = ["Music", "Movies"]
    templates = [music, *movie_like]
    sub = infer_subcategory_for_package(templates, "movies", aliases=aliases)
    assert sub == "Movies"


def test_infer_subcategory_for_package_tie_goes_to_humanized_key():
    music = QuestionTemplate(
        id="music-mc-01",
        subcategory="Music",
        question_family="event",
        question="Q?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
    )
    movies = QuestionTemplate(
        id="movie-yn-01",
        subcategory="Movies",
        question_family="event",
        question="Q?",
        answer_type="yes_no",
        answer_options="Yes||No",
        priority="",
        requires_entities=False,
    )
    aliases = ["Music", "Movies"]
    sub = infer_subcategory_for_package([music, movies], "movies", aliases=aliases)
    assert sub == humanize_package_key("movies")
    assert sub == "Movies"


def test_filter_templates_for_package_accepts_aliases():
    templates = [_event_tpl()]
    out = filter_templates_for_package(templates, "baseball", aliases=["MLB"])
    assert [t.id for t in out] == ["t1"]


def test_package_aliases_for_settings_normalizes_package_keys():
    settings = {"inputs": {"package_aliases": {"formula_one": ["F1", "Formula 1"]}}}
    assert package_aliases_for_settings(settings, "Formula-One") == ["F1", "Formula 1"]
