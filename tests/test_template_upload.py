"""Template upload parsing helpers."""

from __future__ import annotations

import pytest

from core.template_config.schema import parse_template_dict
from core.template_upload import parse_template_csv_blocks, parse_uploaded_template_file


def test_parse_template_csv_blocks_single_template():
    text = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "mlb_game_winner,MLB,event,Who wins?,yes_no,Yes||No,1,false\n"
    )
    rows = parse_template_csv_blocks(text)
    assert rows == [
        {
            "id": "mlb_game_winner",
            "subcategory": "MLB",
            "question_family": "event",
            "question": "Who wins?",
            "answer_type": "yes_no",
            "answer_options": "Yes||No",
            "priority": 1,
            "requires_entities": False,
        }
    ]


def test_parse_template_csv_blocks_multiple_templates():
    text = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "mlb_game_winner,MLB,event,Who wins?,yes_no,Yes||No,1,false\n"
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,stat_column,top_n_per_team\n"
        "mlb_home_run,MLB,entity_stat,Who hits a HR?,multiple_choice,{entity_options},,true,HR,3\n"
    )
    rows = parse_template_csv_blocks(text)
    assert [row["id"] for row in rows] == ["mlb_game_winner", "mlb_home_run"]
    assert rows[1]["requires_entities"] is True
    assert rows[1]["top_n_per_team"] == 3


def test_parse_template_csv_blocks_rejects_odd_rows():
    text = (
        "id,subcategory\n"
        "mlb_game_winner,MLB\n"
        "id,subcategory\n"
    )
    with pytest.raises(ValueError, match="even number of non-empty rows"):
        parse_template_csv_blocks(text)


def test_parse_uploaded_template_file_rejects_bad_bool():
    text = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "mlb_game_winner,MLB,event,Who wins?,yes_no,Yes||No,,maybe\n"
    )
    with pytest.raises(ValueError, match="boolean"):
        parse_uploaded_template_file("templates.csv", text)


def test_parse_template_csv_blocks_blank_priority_stays_blank():
    text = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "mlb_game_winner,MLB,event,Who wins?,yes_no,Yes||No,,false\n"
    )
    rows = parse_template_csv_blocks(text)
    assert rows[0]["priority"] == ""


def test_parse_stock_template_table_csv():
    text = (
        "Template ID,Template Name,Timeframe,Question Template,Answer Type,Answer Options,Recommended Priority,Notes\n"
        "stocks_daily_close_higher,Daily Close Higher,Daily,Will {ASSET} close higher on {DATE}?,yes_no,,1,Core\n"
        "stocks_daily_direction_mc,Daily Direction,Daily,How will {ASSET} finish?,multiple_choice,Higher||Lower,2,MC\n"
    )

    rows = parse_uploaded_template_file("stocks.csv", text)

    assert [row["id"] for row in rows] == [
        "stocks_daily_close_higher",
        "stocks_daily_direction_mc",
    ]
    assert rows[0]["question_family"] == "stock"
    assert rows[0]["answer_options"] == ""
    assert rows[0]["timeframe"] == "Daily"


def test_parse_content_template_table_csv():
    text = (
        "template_id,subcategory,template_type,answer_type,question_template,answer_options_pattern,"
        "required_dataset_fields,automation_ready,default_priority,notes\n"
        "music-yn-01,Music,Album Debut Ranking,yes_no,"
        "Will [ALBUM_OR_RELEASE] debut on the Billboard 200?,,"
        "album_or_artist; release_date; topic_import_id,Yes,1,Core\n"
        "music-mc-01,Music,Album Comparison,multiple_choice,"
        "Which release will chart higher on the Billboard 200?,[RELEASE_A]||[RELEASE_B],"
        "release_a; release_b; chart_week; topic_import_id,Yes,2,Pairwise\n"
    )

    rows = parse_uploaded_template_file("music-Templates.csv", text)

    assert [row["id"] for row in rows] == ["music-yn-01", "music-mc-01"]
    assert rows[0]["question_family"] == "content"
    assert rows[0]["answer_options"] == ""
    assert rows[1]["template_type"] == "Album Comparison"
    assert rows[1]["required_dataset_fields"] == "release_a; release_b; chart_week; topic_import_id"


def test_parse_content_template_table_includes_resolution_date_rule():
    text = (
        "template_id,subcategory,template_type,answer_type,question_template,answer_options_pattern,"
        "required_dataset_fields,automation_ready,default_priority,resolution_date_rule\n"
        "music-yn-01,Music,Album,yes_no,Will [ALBUM] chart?,,fields,Yes,1,start_date + 7 days\n"
    )
    rows = parse_uploaded_template_file("music.csv", text)
    assert rows[0]["resolution_date_rule"] == "start_date + 7 days"


def test_parse_content_template_table_includes_start_and_expiration_rules():
    text = (
        "template_id,subcategory,template_type,answer_type,question_template,answer_options_pattern,"
        "required_dataset_fields,automation_ready,default_priority,resolution_date_rule,start_date_rule,expiration_date_rule\n"
        "music-yn-01,Music,Album,yes_no,Will [ALBUM] chart?,,fields,Yes,1,,event_date_minus_48_hours,event_datetime\n"
    )
    rows = parse_uploaded_template_file("music.csv", text)
    assert rows[0]["start_date_rule"] == "event_date_minus_48_hours"
    assert rows[0]["expiration_date_rule"] == "event_datetime"


def test_parse_content_template_wide_table_question_and_answer_options_aliases():
    """LLM/Excel exports often use ``question`` and ``answer_options`` (JSON-style names)."""

    text = (
        "template_id,subcategory,question_family,question,answer_type,answer_options,priority,"
        "requires_entities,stat_column,top_n_per_team\n"
        "WNBA-001,WNBA,event,Who will win {home_team} vs {away_team}?,multiple_choice,"
        "{home_team}||{away_team},1,false,,\n"
        "WNBA-011,WNBA,entity_stat,Who scores?,multiple_choice,{entity_options},1,true,PTS,2\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert len(rows) == 2
    assert rows[0]["question_family"] == "event"
    assert rows[0]["question"].startswith("Who will win")
    assert rows[1]["stat_column"] == "PTS"


def test_parse_content_template_wide_table_entity_stat_columns_round_trip_schema():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,"
        "stat_column,top_n_per_team,requires_entities,default_priority\n"
        "WNBA-002,WNBA,entity_stat,multiple_choice,Which player will score in {home_team} vs {away_team}?,"
        ",PTS,2,true,1\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert len(rows) == 1
    assert rows[0]["question_family"] == "entity_stat"
    assert rows[0]["requires_entities"] is True
    assert rows[0]["stat_column"] == "PTS"
    assert rows[0]["top_n_per_team"] == 2
    assert rows[0]["answer_options"] == "{entity_options}"
    parse_template_dict(rows[0])


def test_parse_content_template_wide_table_entity_stat_top_n_alias_defaults():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,"
        "stat_column,top_n,default_priority\n"
        "t1,WNBA,entity_stat,multiple_choice,Who scores?,{entity_options},PTS,4,1\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert rows[0]["top_n_per_team"] == 4


def test_parse_content_template_wide_table_entity_stat_default_top_n_and_options():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,"
        "stat_column,default_priority\n"
        "t1,WNBA,entity_stat,multiple_choice,Who scores?,,PTS,1\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert rows[0]["top_n_per_team"] == 2
    assert rows[0]["answer_options"] == "{entity_options}"


def test_parse_content_template_wide_table_infers_entity_stat_when_stat_column_set():
    text = (
        "template_id,subcategory,answer_type,question_template,answer_options_pattern,stat_column,default_priority\n"
        "t1,WNBA,multiple_choice,Who scores?,,PTS,1\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert rows[0]["question_family"] == "entity_stat"
    assert rows[0]["stat_column"] == "PTS"


def test_parse_content_template_wide_table_event_yes_no_blank_options_becomes_yes_no_pair():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,default_priority\n"
        "e1,WNBA,event,yes_no,Will the home team cover?,,1\n"
    )
    rows = parse_uploaded_template_file("wnba.csv", text)
    assert rows[0]["answer_options"] == "Yes||No"
    parse_template_dict(rows[0])


def test_parse_content_template_wide_table_rejects_requires_entities_true_for_event():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,"
        "requires_entities,default_priority\n"
        "e1,WNBA,event,yes_no,Q,,true,1\n"
    )
    with pytest.raises(ValueError, match="requires_entities true"):
        parse_uploaded_template_file("wnba.csv", text)


def test_parse_content_template_wide_table_rejects_entity_stat_without_stat_column():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,default_priority\n"
        "t1,WNBA,entity_stat,multiple_choice,Who scores?,,1\n"
    )
    with pytest.raises(ValueError, match="stat_column"):
        parse_uploaded_template_file("wnba.csv", text)


def test_parse_content_template_wide_table_rejects_entity_stat_with_requires_entities_false():
    text = (
        "template_id,subcategory,question_family,answer_type,question_template,answer_options_pattern,"
        "stat_column,requires_entities,default_priority\n"
        "t1,WNBA,entity_stat,multiple_choice,Who scores?,,PTS,false,1\n"
    )
    with pytest.raises(ValueError, match="entity_stat"):
        parse_uploaded_template_file("wnba.csv", text)
