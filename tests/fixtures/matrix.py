"""Shared pipeline matrix cases for future-category integration coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest

from core.generation.batch_executor import BatchResult, FailedBatch
from core.generation.deterministic_events import build_deterministic_questions
from core.generation.prompt_builder import GeneratedQuestion, PromptItem
from tests.fixtures.workbooks import (
    write_f1_schedule_minimal,
    write_mlb_schedule_minimal,
    write_mlb_stats_minimal,
)

WorkbookKind = Literal[
    "mlb_minimal",
    "mlb_missing_stats",
    "mlb_unmatched_stats",
    "f1_minimal",
]


@dataclass(frozen=True)
class PipelineMatrixCase:
    """One full-pipeline scenario with isolated files and deterministic generation."""

    case_id: str
    category_key: str
    workbook_kind: WorkbookKind
    templates: list[dict[str, Any]]
    expected_success: bool
    expected_message: str | None = None
    templates_enabled: dict[str, bool] = field(default_factory=dict)
    file_roles: dict[str, dict[str, str]] = field(default_factory=dict)
    package_aliases: dict[str, str | list[str]] = field(default_factory=dict)
    package_options: dict[str, Any] = field(default_factory=dict)
    topic_import_ids: dict[str, str] = field(default_factory=dict)
    batch_size: int | str = 100
    max_generated_questions: int | None = None
    fake_fail_batches: frozenset[int] = frozenset()
    fake_invalid_indices: frozenset[int] = frozenset()
    fake_duplicate_questions: bool = False
    event_use_llm: bool = False
    expected_output_rows: int | None = None
    expected_invalid_rows: int = 0
    expected_failed_batches: int = 0
    exhaustive: bool = False


def event_template(
    template_id: str,
    subcategory: str,
    *,
    answer_type: str = "multiple_choice",
) -> dict[str, Any]:
    answer_options = "Yes||No" if answer_type == "yes_no" else "{home_team}||{away_team}"
    return {
        "id": template_id,
        "subcategory": subcategory,
        "question_family": "event",
        "question": "Who will win {home_team} vs {away_team}?",
        "answer_type": answer_type,
        "answer_options": answer_options,
        "priority": 1,
        "requires_entities": False,
    }


def entity_template(template_id: str, subcategory: str, stat_column: str = "HR") -> dict[str, Any]:
    return {
        "id": template_id,
        "subcategory": subcategory,
        "question_family": "entity_stat",
        "question": "Who will hit a home run?",
        "answer_type": "multiple_choice",
        "answer_options": "{entity_options}",
        "priority": "",
        "requires_entities": True,
        "stat_column": stat_column,
        "top_n_per_team": 1,
    }


def write_case_inputs(case: PipelineMatrixCase, input_dir: Path) -> dict[str, dict[str, str]]:
    """Create workbook files for a matrix case and return ``inputs.files``."""

    input_dir.mkdir(parents=True, exist_ok=True)
    if case.workbook_kind == "mlb_minimal":
        write_mlb_schedule_minimal(input_dir / "schedule.xlsx")
        write_mlb_stats_minimal(input_dir / "stats.xlsx")
        return {case.category_key: {"event_source": "schedule.xlsx", "metric_source": "stats.xlsx"}}
    if case.workbook_kind == "mlb_missing_stats":
        write_mlb_schedule_minimal(input_dir / "schedule.xlsx")
        return {case.category_key: {"event_source": "schedule.xlsx", "metric_source": "missing_stats.xlsx"}}
    if case.workbook_kind == "mlb_unmatched_stats":
        write_mlb_schedule_minimal(input_dir / "schedule.xlsx")
        write_mlb_stats_minimal(
            input_dir / "stats.xlsx",
            rows=[
                {"Player": "Other Team Slugger", "Team": "SEA", "HR": 20, "RBI": 60, "SB": 4, "WAR": 3.0}
            ],
        )
        return {case.category_key: {"event_source": "schedule.xlsx", "metric_source": "stats.xlsx"}}
    if case.workbook_kind == "f1_minimal":
        write_f1_schedule_minimal(input_dir / "f1_schedule.xlsx")
        return {case.category_key: {"schedule": "f1_schedule.xlsx"}}
    raise AssertionError(f"Unhandled workbook kind: {case.workbook_kind}")


def write_case_templates(case: PipelineMatrixCase, template_dir: Path) -> None:
    """Write template JSON files for a matrix case."""

    import json

    template_dir.mkdir(parents=True, exist_ok=True)
    for template in case.templates:
        path = template_dir / f"{template['id']}.json"
        path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


def matrix_settings(
    case: PipelineMatrixCase,
    *,
    input_dir: Path,
    template_dir: Path,
    inputs_files: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build isolated settings for a matrix case."""

    inputs: dict[str, Any] = {
        "directory": str(input_dir),
        "category_key": case.category_key,
        "files": inputs_files,
        "packages": case.package_options,
    }
    if case.file_roles:
        inputs["file_roles"] = case.file_roles
    if case.package_aliases:
        inputs["package_aliases"] = case.package_aliases
    return {
        "openai_api_key": "sk-test",
        "model": "gpt-test",
        "topic_import_id": "default-topic",
        "topic_import_ids": case.topic_import_ids,
        "subcategory": case.category_key,
        "top_n_per_team": 2,
        "templates_directory": str(template_dir),
        "templates_enabled": case.templates_enabled,
        "date_filter": {"start": "2026-01-01", "end": "2026-12-31"},
        "date_rules": {
            "default": {
                "start_offset_hours": -24,
                "expiration_offset_hours": 0,
                "resolution_offset_hours": 4,
            }
        },
        "batch_size": case.batch_size,
        "max_generated_questions": case.max_generated_questions,
        "event_generation": {"use_llm": case.event_use_llm},
        "inputs": inputs,
        "parsing": {"persist_profiles": False},
        "_fake_generation": {
            "fail_batches": sorted(case.fake_fail_batches),
            "invalid_indices": sorted(case.fake_invalid_indices),
            "duplicate_questions": case.fake_duplicate_questions,
        },
    }


class FakeBatchExecutor:
    """Deterministic stand-in that preserves production batch metadata semantics."""

    def __init__(self, settings: dict[str, Any], prompt_builder: Any = None) -> None:
        self.settings = settings
        self.batch_size = max(1, int(settings.get("batch_size", 100)))

    def execute(self, items: list[PromptItem], *, on_batch_done: Any = None) -> BatchResult:
        fake = self.settings.get("_fake_generation") or {}
        fail_batches = {int(i) for i in fake.get("fail_batches", [])}
        invalid_indices = {int(i) for i in fake.get("invalid_indices", [])}
        duplicate_questions = bool(fake.get("duplicate_questions", False))
        batches = [items[i : i + self.batch_size] for i in range(0, len(items), self.batch_size)]
        result = BatchResult(total_batches=len(batches))
        global_index = 0
        for batch_index, batch in enumerate(batches):
            if batch_index in fail_batches:
                result.failed_batches.append(
                    FailedBatch(
                        batch_index=batch_index,
                        item_count=len(batch),
                        error=f"fake failure for batch {batch_index}",
                    )
                )
            else:
                for item in batch:
                    gen = build_deterministic_questions([item])[0]
                    if global_index in invalid_indices:
                        gen = gen.model_copy(update={"question": ""})
                    elif duplicate_questions:
                        suffix = "!" if item.template.id.endswith("_b") else "?"
                        gen = gen.model_copy(
                            update={
                                "question": f"Will this repeated question be flagged{suffix}"
                            }
                        )
                    result.questions.append(gen)
                    global_index += 1
                result.successful_batches += 1
            if on_batch_done is not None:
                on_batch_done(batch_index + 1, len(batches))
        return result


def pipeline_matrix_params() -> list[Any]:
    cases = [
        PipelineMatrixCase(
            case_id="mlb_event_and_entity_success",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[
                event_template("mlb_game_winner_matrix", "MLB"),
                entity_template("mlb_home_run_matrix", "MLB"),
            ],
            expected_success=True,
            expected_output_rows=4,
        ),
        PipelineMatrixCase(
            case_id="f1_package_alias_success",
            category_key="formula_one",
            workbook_kind="f1_minimal",
            file_roles={"formula_one": {"schedule": "event_source"}},
            package_aliases={"formula_one": ["F1", "Formula 1"]},
            package_options={
                "f1": {
                    "race_session_values": ["Race"],
                    "placeholder_home_team": "Driver_A",
                    "placeholder_away_team": "Driver_B",
                }
            },
            topic_import_ids={"formula_one": "f1-race-winner"},
            templates=[event_template("f1_alias_winner_matrix", "F1", answer_type="yes_no")],
            expected_success=True,
            expected_output_rows=1,
        ),
        PipelineMatrixCase(
            case_id="mlb_entity_template_no_players",
            category_key="mlb",
            workbook_kind="mlb_unmatched_stats",
            templates=[entity_template("mlb_no_players_matrix", "MLB")],
            expected_success=False,
            expected_message="No prompt items",
        ),
        PipelineMatrixCase(
            case_id="missing_metric_file",
            category_key="mlb",
            workbook_kind="mlb_missing_stats",
            templates=[event_template("mlb_missing_file_matrix", "MLB")],
            expected_success=True,
            expected_output_rows=2,
        ),
        PipelineMatrixCase(
            case_id="invalid_source_role",
            category_key="f1",
            workbook_kind="f1_minimal",
            file_roles={"f1": {"schedule": "bogus_role"}},
            templates=[event_template("f1_invalid_role_matrix", "F1")],
            expected_success=False,
            expected_message="invalid_source_role",
        ),
        PipelineMatrixCase(
            case_id="no_enabled_templates",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[event_template("mlb_disabled_matrix", "MLB")],
            templates_enabled={"mlb_disabled_matrix": False},
            expected_success=False,
            expected_message="No enabled templates",
        ),
        PipelineMatrixCase(
            case_id="partial_batch_failure_keeps_alignment",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[event_template("mlb_partial_batch_matrix", "MLB")],
            batch_size=1,
            event_use_llm=True,
            fake_fail_batches=frozenset({0}),
            expected_success=True,
            expected_output_rows=1,
            expected_failed_batches=1,
        ),
        PipelineMatrixCase(
            case_id="all_batches_failed",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[event_template("mlb_all_failed_matrix", "MLB")],
            batch_size=1,
            event_use_llm=True,
            fake_fail_batches=frozenset({0, 1}),
            expected_success=False,
            expected_message="All generation batches failed",
            expected_failed_batches=2,
        ),
        PipelineMatrixCase(
            case_id="invalid_generated_row_writes_errors",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[event_template("mlb_invalid_row_matrix", "MLB")],
            event_use_llm=True,
            fake_invalid_indices=frozenset({0}),
            expected_success=True,
            expected_output_rows=1,
            expected_invalid_rows=1,
        ),
        PipelineMatrixCase(
            case_id="near_duplicate_questions_flagged",
            category_key="mlb",
            workbook_kind="mlb_minimal",
            templates=[
                event_template("mlb_near_duplicate_matrix_a", "MLB"),
                event_template("mlb_near_duplicate_matrix_b", "MLB"),
            ],
            fake_duplicate_questions=True,
            expected_success=True,
            expected_output_rows=4,
            exhaustive=True,
        ),
    ]
    params = []
    for case in cases:
        marks = [pytest.mark.exhaustive] if case.exhaustive else []
        params.append(pytest.param(case, id=case.case_id, marks=marks))
    return params
