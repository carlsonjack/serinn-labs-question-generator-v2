"""Generic content-list generation tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from core.csv_export import CSV_WRITE_ENCODING, write_import_csv
from core.generation.content import CONTENT_OUTPUT_COLUMNS, ContentPlanner
from core.parsers.contracts import ContentEntity
from core.pipeline import run_pipeline
from core.schema_validator import validate_import_rows
from core.template_config.schema import QuestionTemplate, parse_template_dict
from core.template_upload import parse_uploaded_template_file


def _release(title: str, artist: str, release_date: str) -> ContentEntity:
    return ContentEntity(
        entity_id=f"{title}-{artist}".lower().replace(" ", "-"),
        display_name=f"{title} by {artist}",
        entity_type="music_release",
        metadata={
            "title": title,
            "artist": artist,
            "release_date": release_date,
            "genre": "Pop",
        },
    )


def _movie(title: str, release_date: str) -> ContentEntity:
    return ContentEntity(
        entity_id=title.lower().replace(" ", "-"),
        display_name=title,
        entity_type="content",
        metadata={"title": title, "release_date": release_date, "studio": "A24"},
    )


def _template(
    tid: str,
    question: str,
    *,
    answer_type: str = "yes_no",
    answer_options: str = "",
    template_type: str = "",
    priority: int = 1,
) -> QuestionTemplate:
    return QuestionTemplate(
        id=tid,
        subcategory="Music",
        question_family="content",
        question=question,
        answer_type=answer_type,
        answer_options=answer_options,
        priority=priority,
        requires_entities=False,
        template_type=template_type,
    )


def test_content_planner_fills_single_pairwise_and_static_music_rows() -> None:
    entities = [
        _release("Sanctuary", "Evanescence", "June 5, 2026"),
        _release("BITCH", "Lizzo", "June 5, 2026"),
        _release("Dinner Party", "Niall Horan", "June 5, 2026"),
    ]
    templates = [
        _template("music-yn-01", "Will [ALBUM_OR_RELEASE] debut on the Billboard 200?"),
        _template(
            "music-mc-02",
            "How long will [ALBUM_OR_RELEASE] stay on the [CHART_NAME]?",
            answer_type="multiple_choice",
            answer_options="1-2 weeks||3-6 weeks||6-12 weeks||12+ weeks",
            template_type="Chart Longevity",
            priority=2,
        ),
        _template(
            "music-mc-01",
            "Which release will chart higher on the Billboard 200?",
            answer_type="multiple_choice",
            answer_options="[RELEASE_A]||[RELEASE_B]",
            template_type="Album Comparison",
            priority=2,
        ),
        _template(
            "music-tour-mc-01",
            "Which artist will have the highest-grossing tour of [YEAR] according to [TOUR_CHART_SOURCE]?",
            answer_type="multiple_choice",
            answer_options="[ARTIST_A]||[ARTIST_B]||[ARTIST_C]||[ARTIST_D]",
            template_type="Concert Tour Gross",
            priority=1,
        ),
    ]

    rows = ContentPlanner(
        entities,
        templates,
        {
            "date_filter": {"start": "2026-06-01", "end": "2026-06-30"},
            "content": {"static_resolution_date": "2027-01-10"},
        },
        topic_import_id="music-new-releases-us-2026-06",
    ).generate()

    assert len(rows) == 10
    debut = next(row for row in rows if row.question == "Will BITCH by Lizzo debut on the Billboard 200?")
    assert debut.answer_options == ""
    assert (debut.start_date, debut.expiration_date, debut.resolution_date) == (
        "2026-05-29T00:00:00",
        "2026-06-04T00:00:00",
        "2026-06-19T00:00:00",
    )
    longevity = next(row for row in rows if row.question.startswith("How long will BITCH by Lizzo"))
    assert longevity.resolution_date == "2026-09-03T00:00:00"
    comparison = next(row for row in rows if row.answer_options == "BITCH by Lizzo||Dinner Party by Niall Horan")
    assert comparison.resolution_date == "2026-06-19T00:00:00"
    static = next(row for row in rows if "highest-grossing tour" in row.question)
    assert static.answer_options == "Taylor Swift||Bad Bunny||Beyonce||Coldplay"
    assert static.resolution_date == "2027-01-10T00:00:00"
    assert validate_import_rows(rows) == []


def test_content_planner_supports_movie_alias_and_multi_entity_choice() -> None:
    entities = [
        _movie("Alpha", "May 15, 2026"),
        _movie("Bravo", "May 15, 2026"),
        _movie("Charlie", "May 15, 2026"),
        _movie("Delta", "May 15, 2026"),
    ]
    templates = [
        QuestionTemplate(
            id="movie-yn-01",
            subcategory="Movies",
            question_family="content",
            question="Will [MOVIE_TITLE] be the #1 movie at the US box office this weekend?",
            answer_type="yes_no",
            answer_options="",
            priority=1,
            requires_entities=False,
        ),
        QuestionTemplate(
            id="manual-mc-01",
            subcategory="Movies",
            question_family="content",
            question="Which movie will be #1 at the US box office this weekend?",
            answer_type="multiple_choice",
            answer_options="[MOVIE_A]||[MOVIE_B]||[MOVIE_C]||[MOVIE_D]",
            priority=1,
            requires_entities=False,
            generation_strategy="multi_entity_choice",
            entity_count=4,
        ),
    ]

    rows = ContentPlanner(
        entities,
        templates,
        {"date_filter": {"start": "2026-05-01", "end": "2026-05-31"}},
        topic_import_id="movies-boxoffice-us-2026-05",
    ).generate()

    assert any(
        row.question == "Will Alpha be the #1 movie at the US box office this weekend?"
        for row in rows
    )
    choice = next(row for row in rows if row.question.startswith("Which movie"))
    assert choice.answer_options == "Alpha||Bravo||Charlie||Delta"
    assert validate_import_rows(rows) == []


def test_content_planner_uses_resolution_date_spec_for_resolution() -> None:
    entities = [_release("X", "Y", "June 5, 2026")]
    tpl = QuestionTemplate(
        id="spec-test",
        subcategory="Music",
        question_family="content",
        question="Will [ALBUM_OR_RELEASE] chart?",
        answer_type="yes_no",
        answer_options="",
        priority=1,
        requires_entities=False,
        resolution_date_spec={
            "kind": "offset_from_anchor",
            "anchor": "release_date",
            "offset_days": 1,
            "offset_hours": 0,
        },
    )
    rows = ContentPlanner(
        entities,
        [tpl],
        {"date_filter": {"start": "2026-06-01", "end": "2026-06-30"}},
        topic_import_id="tid",
    ).generate()
    assert len(rows) == 1
    assert rows[0].resolution_date == "2026-06-06T00:00:00"


def test_content_planner_start_spec_offset_hours_emits_clock_time() -> None:
    entities = [_release("X", "Y", "June 5, 2026")]
    tpl = QuestionTemplate(
        id="time-start",
        subcategory="Music",
        question_family="content",
        question="Will [ALBUM_OR_RELEASE] chart?",
        answer_type="yes_no",
        answer_options="",
        priority=1,
        requires_entities=False,
        start_date_spec={
            "kind": "offset_from_anchor",
            "anchor": "release_date",
            "offset_days": 0,
            "offset_hours": -12,
        },
    )
    rows = ContentPlanner(
        entities,
        [tpl],
        {"date_filter": {"start": "2026-06-01", "end": "2026-06-30"}},
        topic_import_id="tid",
    ).generate()
    assert len(rows) == 1
    assert rows[0].start_date == "2026-06-04T12:00:00"
    assert rows[0].expiration_date == "2026-06-04T00:00:00"
    assert validate_import_rows(rows) == []


def test_content_calendar_resolution_may_precede_expiration() -> None:
    """Calendar-based resolution (e.g. nomination season) may fall before title expiration."""

    entity = ContentEntity(
        entity_id="show-late",
        display_name="Survival of the Thickest",
        entity_type="content",
        metadata={
            "title": "Survival of the Thickest (Final S3)",
            "release_date": "2026-10-15",
        },
    )
    tpl = QuestionTemplate(
        id="stream-award-mc-01",
        subcategory="Television",
        question_family="content",
        question="How many Emmy nominations will [TITLE] receive?",
        answer_type="multiple_choice",
        answer_options="0||1||2||3 or more",
        priority=1,
        requires_entities=False,
        resolution_date_spec={
            "kind": "calendar_in_year",
            "calendar_month": 7,
            "calendar_day": 1,
            "year_policy": "release_year",
        },
    )
    rows = ContentPlanner(
        [entity],
        [tpl],
        {"date_filter": {"start": "2026-01-01", "end": "2026-12-31"}},
        topic_import_id="tv-test",
    ).generate()
    assert len(rows) == 1
    row = rows[0]
    assert row.expiration_date == "2026-10-14T00:00:00"
    assert row.resolution_date == "2026-07-01T00:00:00"
    assert validate_import_rows(rows) == []


def test_write_import_csv_uses_titled_headers(tmp_path: Path) -> None:
    rows = ContentPlanner(
        [_release("BITCH", "Lizzo", "June 5, 2026")],
        [_template("music-yn-01", "Will [ALBUM_OR_RELEASE] debut on the Billboard 200?")],
        {"date_filter": {"start": "2026-06-01", "end": "2026-06-30"}},
        topic_import_id="music-new-releases-us-2026-06",
    ).generate()

    out = write_import_csv(rows, tmp_path / "music.csv")

    with out.open(encoding=CSV_WRITE_ENCODING) as fh:
        reader = csv.DictReader(fh)
        exported = list(reader)
    assert reader.fieldnames == CONTENT_OUTPUT_COLUMNS
    assert exported[0]["Topic Import ID"] == "music-new-releases-us-2026-06"
    assert exported[0]["Answer Options"] == ""


def test_music_sample_row_count_matches_supplied_csv_shape() -> None:
    releases = [
        ("Sanctuary", "Evanescence", "June 5, 2026"),
        ("BITCH", "Lizzo", "June 5, 2026"),
        ("Dinner Party", "Niall Horan", "June 5, 2026"),
        ("Cry Baby", "Vince Staples", "June 5, 2026"),
        ("Be Sweet to Me", "Violet Grohl", "June 5, 2026"),
        ("you seem pretty sad for a girl so in love", "Olivia Rodrigo", "June 12, 2026"),
        ("Dirty Blonde", "Bebe Rexha", "June 12, 2026"),
        ("Kehlani", "Kehlani", "June 12, 2026"),
        ("Kicking My Feet & Screaming", "Ruel", "June 12, 2026"),
        ("can we do it all again?", "Sonny Fodera", "June 12, 2026"),
        ("Night at the Opera", "Emei", "June 12, 2026"),
        ("Flow State", "Keith Urban", "June 12, 2026"),
        ("Stages", "Midland", "June 12, 2026"),
        ("It's Been Awful", "Isaiah Rashad", "June 19, 2026"),
        ("Middle of Nowhere", "Kacey Musgraves", "June 19, 2026"),
        ("Maitreya Corso", "Maya Hawke", "June 19, 2026"),
        ("The Big Blue", "Danny Golden", "June 24, 2026"),
        ("Victory", "Madeon", "June 26, 2026"),
        ("Reality Awaits", "The Strokes", "June 26, 2026"),
        ("In Times of Dragons", "Tori Amos", "June 26, 2026"),
        ("Banks of the Trinity", "Cody Johnson", "June 26, 2026"),
    ]
    entities = [_release(title, artist, release_date) for title, artist, release_date in releases]
    template_csv = (
        "template_id,subcategory,template_type,answer_type,question_template,answer_options_pattern,"
        "required_dataset_fields,automation_ready,default_priority,notes\n"
        "music-yn-01,Music,Album Debut Ranking,yes_no,Will [ALBUM_OR_RELEASE] debut on the Billboard 200?,,"
        "album_or_artist; release_date; topic_import_id,Yes,1,Core music release template.\n"
        "music-yn-02,Music,Top 10 Album Debut,yes_no,Will [ALBUM_OR_ARTIST] debut in the Top 25 on the Billboard 200?,,"
        "album_or_artist; release_date; topic_import_id,Yes,2,Strong broad music template.\n"
        "music-mc-02,Music,Chart Longevity,multiple_choice,How long will [ALBUM_OR_RELEASE] stay on the [CHART_NAME]?,"
        "1-2 weeks||3-6 weeks||6-12 weeks||12+ weeks,album_or_release; chart_name; release_date; topic_import_id,,2,\n"
        "music-mc-01,Music,Album Comparison,multiple_choice,Which release will chart higher on the Billboard 200?,"
        "[RELEASE_A]||[RELEASE_B],release_a; release_b; chart_week; topic_import_id,Yes,2,Preferred MC music template.\n"
        "music-mc-03,Music,Album Peak Position,multiple_choice,What will be the peak Billboard 200 chart position for [ALBUM_OR_RELEASE]?,"
        "#1||#2-10||#11-25||Outside Top 25,album_or_release; release_date; topic_import_id,Yes,2,Resolves after chart history is available.\n"
        "music-mc-04,Music,Album Song Count,multiple_choice,How many songs from [ALBUM_OR_RELEASE] will make the Billboard Hot 100 during its first 30 days of release?,"
        "0 songs||1-2 songs||3-5 songs||6+ songs,album_or_release; release_date; topic_import_id,Yes,2,Resolution date: 31 days after release.\n"
        "music-award-01,Music,Award Nomination,yes_no,Will [ALBUM_OR_ARTIST] be nominated for Album of the Year at the Grammy Awards?,,"
        "album_or_artist; release_date; estimated_nomination_date; topic_import_id,Yes,2,Activates during release cycle but resolves during Grammy nominations.\n"
        "music-tour-mc-01,Music,Concert Tour Gross,multiple_choice,Which artist will have the highest-grossing tour of [YEAR] according to [TOUR_CHART_SOURCE]?,"
        "[ARTIST_A]||[ARTIST_B]||[ARTIST_C]||[ARTIST_D],year; tour_chart_source; artist_a; artist_b; artist_c; artist_d; topic_import_id,Yes,1,Long-horizon question.\n"
    )
    templates = [
        parse_template_dict(row)
        for row in parse_uploaded_template_file("music-Templates.csv", template_csv)
    ]

    rows = ContentPlanner(
        entities,
        templates,
        {
            "date_filter": {"start": "2026-06-01", "end": "2026-06-30"},
            "content": {"static_resolution_date": "2027-01-10"},
        },
        topic_import_id="music-new-releases-us-2026-06",
    ).generate()

    assert len(rows) == 174
    assert validate_import_rows(rows) == []


def test_music_pipeline_routes_content_templates_without_openai(tmp_path: Path, monkeypatch) -> None:
    inputs_dir = tmp_path / "inputs"
    templates_dir = tmp_path / "templates"
    outputs_dir = tmp_path / "outputs"
    inputs_dir.mkdir()
    templates_dir.mkdir()
    (inputs_dir / "releases.csv").write_text(
        "Release Date,Album Title,Artist,Genre\n"
        "\"June 5, 2026\",BITCH,Lizzo,Pop / Hip-Hop\n",
        encoding="utf-8",
    )
    (templates_dir / "music.json").write_text(
        json.dumps(
            {
                "id": "music-yn-01",
                "subcategory": "Music",
                "question_family": "content",
                "question": "Will [ALBUM_OR_RELEASE] debut on the Billboard 200?",
                "answer_type": "yes_no",
                "answer_options": "",
                "priority": 1,
                "requires_entities": False,
                "template_type": "Album Debut Ranking",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", outputs_dir)

    result = run_pipeline(
        {
            "openai_api_key": "",
            "templates_directory": str(templates_dir),
            "topic_import_ids": {"music": "music-new-releases-us-2026-06"},
            "templates_enabled": {"music-yn-01": True},
            "date_filter": {"start": "2026-06-01", "end": "2026-06-30"},
            "inputs": {
                "directory": str(inputs_dir),
                "category_key": "music",
                "files": {"music": {"releases": "releases.csv"}},
                "file_roles": {"music": {"releases": "entity_source"}},
                "package_aliases": {"music": ["Music"]},
            },
            "parsing": {"persist_profiles": False},
        },
        category_key="music",
    )

    assert result.success
    assert result.batch_result is not None
    assert result.batch_result.total_batches == 0
    assert result.output_csv is not None
    with result.output_csv.open(encoding=CSV_WRITE_ENCODING) as fh:
        exported = list(csv.DictReader(fh))
    assert exported[0]["Question"] == "Will BITCH by Lizzo debut on the Billboard 200?"
