"""Template placeholder normalization tests."""

from __future__ import annotations

import pytest

from core.parsers.contracts import ContentEntity
from core.template_placeholder_mapper import (
    extract_placeholders_from_template,
    normalize_template_for_upload,
)


def _movie(title: str) -> ContentEntity:
    return ContentEntity(
        entity_id=title.lower(),
        display_name=title,
        metadata={"title": title, "release_date": "2026-05-15", "studio": "A24"},
    )


def test_extract_placeholders_from_question_and_answers() -> None:
    data = {
        "question": "Will [MOVIE_TITE] beat {MOVIE_B}?",
        "answer_options": "[MOVIE_A]||[MOVIE_B]",
    }

    assert extract_placeholders_from_template(data) == {"MOVIE_TITE", "MOVIE_A", "MOVIE_B"}


def test_normalize_template_for_upload_maps_movie_title_typo() -> None:
    result = normalize_template_for_upload(
        {
            "id": "movie-yn-01",
            "subcategory": "Movies",
            "question_family": "content",
            "question": "Will [MOVIE_TITE] open at #1?",
            "answer_type": "yes_no",
            "answer_options": "",
            "priority": 1,
            "requires_entities": False,
        },
        {"openai_api_key": ""},
        category_key="movies",
        entities=[_movie("Alpha")],
    )

    assert result.data["question"] == "Will [TITLE] open at #1?"
    assert result.data["placeholder_mappings"]["MOVIE_TITE"]["canonical_placeholder"] == "TITLE"
    assert "Mapped [MOVIE_TITE] to [TITLE]." in result.warnings


def test_normalize_template_for_upload_detects_multi_entity_choices() -> None:
    result = normalize_template_for_upload(
        {
            "id": "movie-mc-01",
            "subcategory": "Movies",
            "question_family": "content",
            "question": "Which movie wins?",
            "answer_type": "multiple_choice",
            "answer_options": "[MOVIE_A]||[MOVIE_B]||[MOVIE_C]||[MOVIE_D]",
            "priority": 1,
            "requires_entities": False,
        },
        {"openai_api_key": ""},
        category_key="movies",
        entities=[_movie("A"), _movie("B"), _movie("C"), _movie("D")],
    )

    assert result.data["answer_options"] == "[ENTITY_A]||[ENTITY_B]||[ENTITY_C]||[ENTITY_D]"
    assert result.data["generation_strategy"] == "multi_entity_choice"
    assert result.data["entity_count"] == 4


def test_normalize_template_for_upload_rejects_unknown_placeholder() -> None:
    with pytest.raises(ValueError, match="Unknown template placeholder"):
        normalize_template_for_upload(
            {
                "id": "bad",
                "subcategory": "Movies",
                "question_family": "content",
                "question": "Will [BOX_OFFICE_SECRET] happen?",
                "answer_type": "yes_no",
                "answer_options": "",
                "priority": 1,
                "requires_entities": False,
            },
            {"openai_api_key": ""},
            category_key="movies",
            entities=[_movie("Alpha")],
        )
