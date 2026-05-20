"""Cross-stage pipeline matrix covering future-category extension contracts."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from core.csv_export import CSV_WRITE_ENCODING
from core.pipeline import run_pipeline
from tests.fixtures.matrix import (
    FakeBatchExecutor,
    PipelineMatrixCase,
    matrix_settings,
    pipeline_matrix_params,
    write_case_inputs,
    write_case_templates,
)


@pytest.mark.integration
@pytest.mark.parametrize("case", pipeline_matrix_params())
def test_pipeline_matrix_cases(
    case: PipelineMatrixCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "inputs"
    template_dir = tmp_path / "templates"
    output_dir = tmp_path / "outputs"
    profile_dir = tmp_path / "profiles"
    inputs_files = write_case_inputs(case, input_dir)
    write_case_templates(case, template_dir)
    _write_case_profiles(case, profile_dir)
    settings = matrix_settings(
        case,
        input_dir=input_dir,
        template_dir=template_dir,
        inputs_files=inputs_files,
    )

    monkeypatch.setattr("core.pipeline.DEFAULT_OUTPUT_DIR", output_dir)
    monkeypatch.setattr("core.parsers.profiles._PROFILE_DIR", profile_dir)
    monkeypatch.setattr("core.pipeline.BatchExecutor", FakeBatchExecutor)

    result = run_pipeline(settings, category_key=case.category_key)

    assert result.success is case.expected_success
    if case.expected_message:
        assert result.message is not None
        assert case.expected_message in result.message
    if result.batch_result is not None:
        assert len(result.batch_result.failed_batches) == case.expected_failed_batches

    if not case.expected_success:
        assert result.output_csv is None
        return

    assert result.output_csv is not None
    assert result.output_csv.parent == output_dir
    with result.output_csv.open(encoding=CSV_WRITE_ENCODING) as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == [
            "topic_import_id",
            "subcategory",
            "event",
            "question",
            "answer_type",
            "answer_options",
            "start_date",
            "expiration_date",
            "resolution_date",
            "priority",
        ]
    rows = _read_csv(result.output_csv)
    if case.expected_output_rows is not None:
        assert len(rows) == case.expected_output_rows
    assert all(row["topic_import_id"] for row in rows)
    assert all(row["priority"] == "" or int(row["priority"]) >= 0 for row in rows)
    assert all(value is not None for row in rows for value in row.values())
    assert all(row["subcategory"] for row in rows)
    assert all("{" not in row["question"] for row in rows)
    assert all("}" not in row["question"] for row in rows)

    if case.expected_invalid_rows:
        assert result.errors_csv is not None
        error_rows = _read_csv(result.errors_csv)
        assert len(error_rows) == case.expected_invalid_rows
    else:
        assert result.errors_csv is None

    if case.fake_duplicate_questions:
        assert result.flagged_csv is None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding=CSV_WRITE_ENCODING) as fh:
        return list(csv.DictReader(fh))


def _write_case_profiles(case: PipelineMatrixCase, profile_dir: Path) -> None:
    if case.workbook_kind != "f1_minimal":
        return
    profile_dir.mkdir(parents=True, exist_ok=True)
    src = (
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "input_profiles"
        / "f1__event-source__f1_schedule.yaml"
    )
    shutil.copy(src, profile_dir / "f1_schedule.yaml")
