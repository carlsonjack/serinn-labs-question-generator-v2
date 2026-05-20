"""Pipeline runs for sports events without OpenAI (deterministic generation)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from tests.fixtures.matrix import (
    PipelineMatrixCase,
    event_template,
    matrix_settings,
    write_case_inputs,
    write_case_templates,
)


@pytest.mark.integration
def test_run_pipeline_mlb_deterministic_no_openai(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path uses template fill only; BatchExecutor must not be invoked."""

    case = PipelineMatrixCase(
        case_id="deterministic_mlb_smoke",
        category_key="mlb",
        workbook_kind="mlb_minimal",
        templates=[event_template("mlb_deterministic_smoke", "MLB")],
        expected_success=True,
        expected_output_rows=2,
        event_use_llm=False,
    )
    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    profile_dir = tmp_path / "profiles"
    inputs_files = write_case_inputs(case, input_dir)
    write_case_templates(case, template_dir)
    settings = matrix_settings(
        case,
        input_dir=input_dir,
        template_dir=template_dir,
        inputs_files=inputs_files,
    )
    settings["openai_api_key"] = ""

    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)
    monkeypatch.setattr("core.parsers.profiles._PROFILE_DIR", profile_dir)

    def _forbid_batch_executor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("BatchExecutor should not run when event_generation.use_llm is false")

    monkeypatch.setattr("core.pipeline.BatchExecutor", _forbid_batch_executor)

    result = run_pipeline(settings, category_key="mlb")

    assert result.success is True
    assert result.output_csv is not None
    with result.output_csv.open(encoding=CSV_WRITE_ENCODING) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert all(" vs " in row["question"] for row in rows)
    assert all("{" not in row["question"] and "[" not in row["question"] for row in rows)
    assert all("||" in row["answer_options"] for row in rows)
