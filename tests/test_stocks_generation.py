"""Stocks MVP normalization and deterministic generation tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from core.csv_export import CSV_WRITE_ENCODING, write_stock_import_csv
from core.generation.stocks import STOCK_OUTPUT_COLUMNS, StockPlanner
from core.market_calendar import stock_question_dates
from core.parsers.contracts import ContentEntity, ValidationSeverity
from core.parsers.service import load_normalized_bundle
from core.pipeline import run_pipeline
from core.schema_validator import validate_stock_row, validate_stock_rows
from core.template_config.schema import QuestionTemplate
from tests.fixtures.workbooks import write_stock_list_minimal


def _stock_settings(tmp_path: Path) -> dict:
    return {
        "topic_import_ids": {"stocks": "stocks-us-market"},
        "inputs": {
            "directory": str(tmp_path),
            "category_key": "stocks",
            "files": {"stocks": {"asset_source": "stocks.csv"}},
            "file_roles": {"stocks": {"asset_source": "entity_source"}},
        },
        "date_filter": {"start": "2026-06-01", "end": "2026-06-02"},
        "parsing": {"persist_profiles": False},
        "stocks": {"questions_per_day": 13},
    }


def _template(
    tid: str,
    question: str,
    *,
    answer_type: str = "yes_no",
    answer_options: str = "",
    timeframe: str = "Daily",
) -> QuestionTemplate:
    return QuestionTemplate(
        id=tid,
        subcategory="stocks",
        question_family="stock",
        question=question,
        answer_type=answer_type,
        answer_options=answer_options,
        priority=1,
        requires_entities=False,
        timeframe=timeframe,
    )


def _entities(n: int = 8) -> list[ContentEntity]:
    return [
        ContentEntity(
            entity_id=f"T{i}",
            display_name=f"Company {i} (T{i})",
            entity_type="stock",
        )
        for i in range(n)
    ]


def test_stocks_normalizer_reads_watchlist(tmp_path: Path) -> None:
    write_stock_list_minimal(tmp_path / "stocks.csv")

    bundle = load_normalized_bundle(_stock_settings(tmp_path), category_key="stocks")

    errors = [i for i in bundle.issues if i.severity == ValidationSeverity.ERROR]
    assert errors == []
    assert [entity.entity_id for entity in bundle.entities[:2]] == ["AAPL", "MSFT"]
    assert bundle.entities[0].display_name == "Apple Inc. (AAPL)"


def test_stocks_normalizer_rejects_duplicate_ticker(tmp_path: Path) -> None:
    write_stock_list_minimal(
        tmp_path / "stocks.csv",
        rows=[
            {"Topic Import ID": "stocks-us-market", "Company Name": "Apple Inc.", "Ticker": "AAPL"},
            {"Topic Import ID": "stocks-us-market", "Company Name": "Apple Duplicate", "Ticker": "AAPL"},
        ],
    )

    bundle = load_normalized_bundle(_stock_settings(tmp_path), category_key="stocks")

    assert any(issue.code == "duplicate_stock_ticker" for issue in bundle.issues)


def test_stock_question_dates_match_client_june_examples() -> None:
    import datetime as dt

    daily = stock_question_dates(dt.date(2026, 6, 1), "Daily")
    assert daily.start_date == "2026-05-30T00:00:00"
    assert daily.expiration_date == "2026-06-01T00:00:00"
    assert daily.resolution_date == "2026-06-02T00:00:00"

    next_daily = stock_question_dates(dt.date(2026, 6, 2), "Daily")
    assert next_daily.start_date == "2026-05-31T00:00:00"
    assert next_daily.expiration_date == "2026-06-02T00:00:00"
    assert next_daily.resolution_date == "2026-06-03T00:00:00"

    weekly = stock_question_dates(dt.date(2026, 6, 1), "Weekly")
    assert weekly.start_date == "2026-05-30T00:00:00"
    assert weekly.expiration_date == "2026-06-01T00:00:00"
    assert weekly.resolution_date == "2026-06-06T00:00:00"

    monthly = stock_question_dates(dt.date(2026, 6, 1), "Monthly")
    assert monthly.start_date == "2026-06-01T00:00:00"
    assert monthly.expiration_date == "2026-06-10T00:00:00"
    assert monthly.resolution_date == "2026-07-01T00:00:00"

    quarterly = stock_question_dates(dt.date(2026, 6, 1), "Quarterly")
    assert quarterly.start_date == "2026-04-01T00:00:00"
    assert quarterly.expiration_date == "2026-04-30T00:00:00"
    assert quarterly.resolution_date == "2026-07-01T00:00:00"


def test_stock_planner_fills_placeholders_and_unique_mc_sets() -> None:
    templates = [
        _template(
            "stocks_daily_close_higher",
            "Will {ASSET} close higher on {DATE}?",
        ),
        _template(
            "stocks_daily_biggest_gainer",
            "Which gains most on {DATE}?",
            answer_type="multiple_choice",
            answer_options="{ASSET_1}||{ASSET_2}||{ASSET_3}||{ASSET_4}||None",
        ),
    ]
    rows = StockPlanner(
        _entities(10),
        templates,
        {"date_filter": {"start": "2026-05-30", "end": "2026-06-01"}, "stocks": {"questions_per_day": 4}},
        topic_import_id="stocks-us-market",
    ).generate()

    assert len(rows) == 4
    assert all("{" not in row.question for row in rows)
    mc_sets = {
        tuple(option for option in row.answer_options.split("||") if option != "None")
        for row in rows
        if row.answer_type == "multiple_choice"
    }
    assert len(mc_sets) == len([row for row in rows if row.answer_type == "multiple_choice"])
    assert any(row.answer_type == "yes_no" and row.answer_options == "" for row in rows)


def test_stock_planner_varies_four_asset_mc_sets_across_trading_days() -> None:
    templates = [
        _template(
            "stocks_daily_biggest_gainer",
            "Which gains most on {DATE}?",
            answer_type="multiple_choice",
            answer_options="{ASSET_1}||{ASSET_2}||{ASSET_3}||{ASSET_4}||None",
        ),
    ]
    rows = StockPlanner(
        _entities(20),
        templates,
        {
            "date_filter": {"start": "2026-05-30", "end": "2026-06-05"},
            "stocks": {"questions_per_day": 1},
        },
        topic_import_id="stocks-us-market",
    ).generate()

    mc_sets = {
        tuple(option for option in row.answer_options.split("||") if option != "None")
        for row in rows
        if row.answer_type == "multiple_choice"
    }
    assert len(rows) >= 3
    assert len(mc_sets) >= 3


def test_stock_planner_respects_top_level_max_generated_questions() -> None:
    """UI saves ``max_generated_questions`` at settings root; stocks must honor it."""

    rows = StockPlanner(
        _entities(20),
        [_template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?")],
        {
            "date_filter": {"start": "2026-05-30", "end": "2026-06-30"},
            "max_generated_questions": 5,
            "stocks": {"questions_per_day": 100},
        },
        topic_import_id="stocks-us-market",
    ).generate()

    assert len(rows) == 5


def test_stock_planner_stocks_max_generated_questions_overrides_top_level() -> None:
    rows = StockPlanner(
        _entities(20),
        [_template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?")],
        {
            "date_filter": {"start": "2026-05-30", "end": "2026-06-30"},
            "max_generated_questions": 100,
            "stocks": {"questions_per_day": 50, "max_generated_questions": 3},
        },
        topic_import_id="stocks-us-market",
    ).generate()

    assert len(rows) == 3


def test_validate_stock_rows_enforces_client_contract() -> None:
    row = StockPlanner(
        _entities(2),
        [_template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?")],
        {"date_filter": {"start": "2026-05-30", "end": "2026-06-01"}, "stocks": {"questions_per_day": 1}},
        topic_import_id="stocks-us-market",
    ).generate()[0]

    assert validate_stock_row(row) == []
    bad = row.__class__(
        topic_import_id=row.topic_import_id,
        question="Will {ASSET} close higher?",
        answer_type="yes_no",
        answer_options="Yes||No",
        start_date=row.start_date,
        expiration_date=row.expiration_date,
        resolution_date=row.resolution_date,
        priority=row.priority,
    )
    assert validate_stock_rows([bad])

    premature_resolution = row.__class__(
        topic_import_id=row.topic_import_id,
        question=row.question,
        answer_type=row.answer_type,
        answer_options=row.answer_options,
        start_date=row.start_date,
        expiration_date=row.expiration_date,
        resolution_date=row.expiration_date,
        priority=row.priority,
    )
    assert validate_stock_row(premature_resolution) == []


def test_write_stock_import_csv_uses_titled_headers(tmp_path: Path) -> None:
    row = StockPlanner(
        _entities(2),
        [_template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?")],
        {"date_filter": {"start": "2026-05-30", "end": "2026-06-01"}, "stocks": {"questions_per_day": 1}},
        topic_import_id="stocks-us-market",
    ).generate()[0]

    out = write_stock_import_csv([row], tmp_path / "stocks.csv")

    with out.open(encoding=CSV_WRITE_ENCODING) as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == STOCK_OUTPUT_COLUMNS
        rows = list(reader)
    assert rows[0]["Topic Import ID"] == "stocks-us-market"
    assert rows[0]["Answer Options"] == ""


def test_stock_export_uses_client_date_windows_and_delayed_resolution(tmp_path: Path) -> None:
    templates = [
        _template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?", timeframe="Daily"),
        _template("stocks_weekly_friday_higher", "Will {ASSET} close higher on Friday?", timeframe="Weekly"),
        _template("stocks_monthly_finish_higher", "Will {ASSET} finish {MONTH} higher?", timeframe="Monthly"),
        _template("stocks_quarterly_end_higher", "Will {ASSET} end Q{QUARTER} higher?", timeframe="Quarterly"),
    ]
    rows = StockPlanner(
        _entities(8),
        templates,
        {
            "date_filter": {"start": "2026-05-30", "end": "2026-06-01"},
            "stocks": {"questions_per_day": 4},
        },
        topic_import_id="stocks-us-market",
    ).generate()

    out = write_stock_import_csv(rows, tmp_path / "stocks.csv")

    with out.open(encoding=CSV_WRITE_ENCODING) as fh:
        exported = list(csv.DictReader(fh))

    assert len(exported) == 3
    assert all(row["Expiration Date"] < row["Resolution Date"] for row in exported)
    assert (exported[0]["Start Date"], exported[0]["Expiration Date"], exported[0]["Resolution Date"]) == (
        "2026-05-30T00:00:00",
        "2026-06-01T00:00:00",
        "2026-06-02T00:00:00",
    )
    assert (exported[1]["Start Date"], exported[1]["Expiration Date"], exported[1]["Resolution Date"]) == (
        "2026-05-30T00:00:00",
        "2026-06-01T00:00:00",
        "2026-06-06T00:00:00",
    )
    assert (exported[2]["Start Date"], exported[2]["Expiration Date"], exported[2]["Resolution Date"]) == (
        "2026-06-01T00:00:00",
        "2026-06-10T00:00:00",
        "2026-07-01T00:00:00",
    )


def test_stock_planner_filters_rows_before_window_start_and_keeps_boundary() -> None:
    templates = [
        _template("stocks_daily_close_higher", "Will {ASSET} close higher on {DATE}?", timeframe="Daily"),
        _template("stocks_monthly_finish_higher", "Will {ASSET} finish {MONTH} higher?", timeframe="Monthly"),
        _template("stocks_quarterly_end_higher", "Will {ASSET} end Q{QUARTER} higher?", timeframe="Quarterly"),
    ]

    rows = StockPlanner(
        _entities(8),
        templates,
        {
            "date_filter": {"start": "2026-06-09", "end": "2026-06-11"},
            "stocks": {"questions_per_day": 3},
        },
        topic_import_id="stocks-us-market",
    ).generate()

    assert [row.start_date for row in rows] == ["2026-06-09T00:00:00"]
    assert rows[0].question.endswith("2026-06-11?")


def test_run_pipeline_stocks_writes_client_csv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    write_stock_list_minimal(input_dir / "stocks.csv")
    template_dir.mkdir()
    (template_dir / "stocks_daily_close_higher.json").write_text(
        json.dumps(
            {
                "id": "stocks_daily_close_higher",
                "subcategory": "stocks",
                "question_family": "stock",
                "question": "Will {ASSET} close higher on {DATE}?",
                "answer_type": "yes_no",
                "answer_options": "",
                "priority": 1,
                "requires_entities": False,
                "timeframe": "Daily",
            }
        ),
        encoding="utf-8",
    )
    settings = _stock_settings(input_dir)
    settings["date_filter"] = {"start": "2026-05-30", "end": "2026-06-01"}
    settings["templates_directory"] = str(template_dir)
    settings["stocks"] = {"questions_per_day": 1}
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)

    result = run_pipeline(settings, category_key="stocks")

    assert result.success is True
    assert result.output_csv is not None
    with result.output_csv.open(encoding=CSV_WRITE_ENCODING) as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == STOCK_OUTPUT_COLUMNS
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["Question"].startswith("Will Apple Inc. (AAPL) close higher")


def test_run_pipeline_stocks_fails_when_min_start_filter_removes_all_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    write_stock_list_minimal(input_dir / "stocks.csv")
    template_dir.mkdir()
    (template_dir / "stocks_quarterly_end_higher.json").write_text(
        json.dumps(
            {
                "id": "stocks_quarterly_end_higher",
                "subcategory": "stocks",
                "question_family": "stock",
                "question": "Will {ASSET} end Q{QUARTER} higher?",
                "answer_type": "yes_no",
                "answer_options": "",
                "priority": 1,
                "requires_entities": False,
                "timeframe": "Quarterly",
            }
        ),
        encoding="utf-8",
    )
    settings = _stock_settings(input_dir)
    settings["date_filter"] = {"start": "2026-05-30", "end": "2026-06-01"}
    settings["templates_directory"] = str(template_dir)
    settings["stocks"] = {"questions_per_day": 1}
    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)

    result = run_pipeline(settings, category_key="stocks")

    assert result.success is False
    assert result.output_csv is None
    assert result.message is not None
    assert "No stock rows remain after applying minimum Start Date" in result.message

