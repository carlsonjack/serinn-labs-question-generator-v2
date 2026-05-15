"""End-to-end generation pipeline (single entry point for CLI and Flask UI)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from core.csv_export import (
    DEFAULT_OUTPUT_DIR,
    write_content_import_csv_auto,
    write_generated_csv_auto,
    write_stock_import_csv_auto,
)
from core.dedup import deduplicate, write_flagged_csv
from core.input_slots import get_inputs_category_key
from core.generation import (
    BatchExecutor,
    BatchResult,
    FailedBatch,
    PromptBuilder,
    PromptItem,
    RowAssembler,
    ContentPlanner,
    StockPlanner,
    resolve_topic_import_id,
)
from core.generation.token_tracker import RunCostSummary
from core.parsers.contracts import (
    NormalizedBundle,
    NormalizedEvent,
    PlayerStatRecord,
    ValidationIssue,
    ValidationSeverity,
)
from core.parsers.mlb.common import TEAM_MAP, normalize_team_name
from core.parsers.service import load_normalized_bundle
from core.qa_summary import QASummary, build_qa_summary
from core.schema_validator import (
    ValidationResult,
    validate_rows,
    validate_import_rows,
    validate_stock_rows,
    write_errors_csv,
)
from core.template_config.loader import load_template_dir, resolve_templates_directory
from core.template_config.schema import QuestionTemplate
from core.template_ui import (
    filter_templates_for_package,
    infer_subcategory_for_package,
    normalize_template_package,
    package_aliases_for_settings,
)

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[str, int, int], None]
"""(phase_message, current_step, total_steps) — total_steps may be 0 if unknown."""


@dataclass
class PipelineResult:
    """Structured outcome of :func:`run_pipeline`."""

    success: bool
    message: str | None = None
    output_csv: Path | None = None
    errors_csv: Path | None = None
    flagged_csv: Path | None = None
    qa_summary: QASummary | None = None
    batch_result: BatchResult | None = None
    validation: ValidationResult | None = None
    parser_warnings: list[str] = field(default_factory=list)


def _chunk_items(items: list[PromptItem], batch_size: int) -> list[list[PromptItem]]:
    size = max(1, batch_size)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _successful_prompt_items(
    items: list[PromptItem], batch_result: BatchResult, batch_size: int
) -> list[PromptItem]:
    failed = {fb.batch_index for fb in batch_result.failed_batches}
    batches = _chunk_items(items, batch_size)
    out: list[PromptItem] = []
    for idx, batch in enumerate(batches):
        if idx not in failed:
            out.extend(batch)
    return out


def _issue_messages(issues: list[ValidationIssue]) -> list[str]:
    return [f"{issue.code}: {issue.message}" for issue in issues]


def _bundle_has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == ValidationSeverity.ERROR for i in issues)


def resolve_top_n_per_team(template: QuestionTemplate, settings: Mapping[str, Any]) -> int:
    override = settings.get("top_n_per_team")
    if override is not None:
        return max(1, int(override))
    if template.top_n_per_team is not None:
        return max(1, int(template.top_n_per_team))
    return 2


def is_template_enabled(template_id: str, settings: Mapping[str, Any]) -> bool:
    te = settings.get("templates_enabled")
    if te is None:
        return True
    if not isinstance(te, dict):
        return True
    return bool(te.get(template_id, True))


def filter_templates_for_subcategory(
    templates: dict[str, QuestionTemplate],
    subcategory: str,
    settings: Mapping[str, Any],
) -> list[QuestionTemplate]:
    sub = (subcategory or "").strip()
    out: list[QuestionTemplate] = []
    for t in templates.values():
        if normalize_template_package(t.subcategory) != normalize_template_package(sub):
            continue
        if not is_template_enabled(t.id, settings):
            continue
        out.append(t)
    return sorted(out, key=lambda x: x.id)


def top_players_for_team(
    player_stats: list[PlayerStatRecord],
    team_label: str,
    stat_column: str,
    n: int,
) -> list[PlayerStatRecord]:
    abbrev = normalize_team_name(TEAM_MAP.get(team_label, team_label))
    stat_key = stat_column.upper()
    candidates = [r for r in player_stats if r.team == abbrev]
    return sorted(
        candidates,
        key=lambda r: (-r.stat_values.get(stat_key, 0.0), r.player_name),
    )[:n]


def _format_generation_failure_message(batch_result: BatchResult) -> str:
    """User-facing message when every API batch failed (e.g. quota, auth)."""

    if not batch_result.failed_batches:
        return "Generation produced no questions (all batches failed)."
    fb: FailedBatch = batch_result.failed_batches[0]
    err = (fb.error or "").strip()
    if len(err) > 1800:
        err = err[:1797] + "…"

    lower = err.lower()
    if "429" in err or "insufficient_quota" in lower or (
        "quota" in lower and "billing" in lower
    ):
        return (
            "OpenAI rejected the request (billing or quota). "
            "Check your API key, plan, and usage at https://platform.openai.com/account/billing "
            f"— detail: {err}"
        )
    if "401" in err or "invalid_api_key" in lower or "incorrect api key" in lower:
        return f"OpenAI API key issue — detail: {err}"
    return f"All generation batches failed. First error: {err}"


def _max_generated_questions(settings: Mapping[str, Any]) -> int | None:
    """Return a positive cap, or ``None`` for no limit."""

    raw = settings.get("max_generated_questions")
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _client_failure(message: str, warnings: list[str] | None = None) -> PipelineResult:
    """Return a structured failure for expected operator/client mistakes."""

    return PipelineResult(
        success=False,
        message=message,
        parser_warnings=warnings or [],
    )


def _is_stocks_package(category_key: str) -> bool:
    return normalize_template_package(category_key) == "stocks"


def _is_content_template_set(templates: list[QuestionTemplate]) -> bool:
    return bool(templates) and all(t.question_family == "content" for t in templates)


def _run_stocks_pipeline(
    *,
    settings: dict[str, Any],
    category_key: str,
    bundle: NormalizedBundle,
    templates: list[QuestionTemplate],
    subcategory: str,
    warnings: list[str],
) -> PipelineResult:
    """Generate deterministic stock rows and write Jim's titled import CSV."""

    try:
        topic_import_id = resolve_topic_import_id(settings, category_key)
        rows = StockPlanner(
            bundle.entities,
            templates,
            settings,
            topic_import_id=topic_import_id,
        ).generate()
    except (TypeError, ValueError) as exc:
        return _client_failure(f"Stocks generation settings error: {exc}", warnings)

    invalid = validate_stock_rows(rows)
    if invalid:
        first_row, reasons = invalid[0]
        return PipelineResult(
            success=False,
            message=(
                "Stock output validation failed: "
                + "; ".join(reasons)
                + f" (question={first_row.question!r})"
            ),
            parser_warnings=warnings,
        )

    date_filter = settings.get("date_filter", {})
    try:
        out_path = write_stock_import_csv_auto(
            rows,
            date_filter=date_filter,
            output_dir=DEFAULT_OUTPUT_DIR,
        )
    except KeyError as exc:
        return PipelineResult(
            success=False,
            message=f"Output configuration error: missing date_filter field {exc}.",
            parser_warnings=warnings,
        )
    except OSError as exc:
        return PipelineResult(
            success=False,
            message=f"Could not write stock output CSV: {exc}",
            parser_warnings=warnings,
        )

    return PipelineResult(
        success=True,
        message=None,
        output_csv=out_path,
        parser_warnings=warnings,
        batch_result=BatchResult(total_batches=0, successful_batches=0),
    )


def _run_content_pipeline(
    *,
    settings: dict[str, Any],
    category_key: str,
    bundle: NormalizedBundle,
    templates: list[QuestionTemplate],
    subcategory: str,
    warnings: list[str],
) -> PipelineResult:
    """Generate deterministic content-list rows and write titled import CSV."""

    try:
        topic_import_id = resolve_topic_import_id(settings, category_key)
        rows = ContentPlanner(
            bundle.entities,
            templates,
            settings,
            topic_import_id=topic_import_id,
        ).generate()
    except (TypeError, ValueError) as exc:
        return _client_failure(f"Content generation settings error: {exc}", warnings)

    invalid = validate_import_rows(rows)
    if invalid:
        first_row, reasons = invalid[0]
        return PipelineResult(
            success=False,
            message=(
                "Content output validation failed: "
                + "; ".join(reasons)
                + f" (question={first_row.question!r})"
            ),
            parser_warnings=warnings,
        )

    date_filter = settings.get("date_filter", {})
    try:
        out_path = write_content_import_csv_auto(
            rows,
            subcategory=subcategory,
            date_filter=date_filter,
            output_dir=DEFAULT_OUTPUT_DIR,
        )
    except KeyError as exc:
        return PipelineResult(
            success=False,
            message=f"Output configuration error: missing date_filter field {exc}.",
            parser_warnings=warnings,
        )
    except OSError as exc:
        return PipelineResult(
            success=False,
            message=f"Could not write content output CSV: {exc}",
            parser_warnings=warnings,
        )

    return PipelineResult(
        success=True,
        message=None,
        output_csv=out_path,
        parser_warnings=warnings,
        batch_result=BatchResult(total_batches=0, successful_batches=0),
    )


def build_prompt_items(
    bundle: NormalizedBundle,
    templates: list[QuestionTemplate],
    settings: Mapping[str, Any],
) -> list[PromptItem]:
    items: list[PromptItem] = []
    for event in bundle.events:
        for tpl in templates:
            if tpl.question_family == "event":
                items.append(PromptItem(template=tpl, event=event, players=[]))
            elif tpl.question_family == "entity_stat":
                n = resolve_top_n_per_team(tpl, settings)
                stat = tpl.stat_column or "HR"
                home_players = top_players_for_team(
                    bundle.player_stats, event.home_team, stat, n
                )
                away_players = top_players_for_team(
                    bundle.player_stats, event.away_team, stat, n
                )
                players = home_players + away_players
                if not players:
                    logger.warning(
                        "Skipping entity template %s for event %s — no players",
                        tpl.id,
                        event.event_id,
                    )
                    continue
                items.append(PromptItem(template=tpl, event=event, players=players))
    return items


def run_pipeline(
    settings: dict[str, Any],
    *,
    category_key: str | None = None,
    progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Load inputs, generate questions, validate, dedupe, and write CSV outputs."""

    def prog(phase: str, cur: int = 0, total: int = 0) -> None:
        if progress:
            progress(phase, cur, total)

    ck = category_key if category_key is not None else get_inputs_category_key(settings)
    try:
        bundle = load_normalized_bundle(settings, category_key=ck)
    except (FileNotFoundError, ValueError) as exc:
        return _client_failure(f"Input configuration error: {exc}")
    warnings = _issue_messages(
        [i for i in bundle.issues if i.severity == ValidationSeverity.WARNING]
    )

    if _bundle_has_errors(bundle.issues):
        msg = "; ".join(_issue_messages(bundle.issues)) or "Input validation failed."
        return PipelineResult(
            success=False,
            message=msg,
            parser_warnings=warnings,
        )

    tpl_dir = resolve_templates_directory(settings)
    try:
        all_templates = load_template_dir(tpl_dir)
    except (FileNotFoundError, ValueError) as exc:
        return _client_failure(f"Template configuration error: {exc}", warnings)
    aliases = package_aliases_for_settings(settings, ck)
    active = [
        t for t in filter_templates_for_package(all_templates.values(), ck, aliases)
        if is_template_enabled(t.id, settings)
    ]
    if not active:
        return PipelineResult(
            success=False,
            message=f"No enabled templates for input package {ck!r}.",
            parser_warnings=warnings,
        )
    subcategory = infer_subcategory_for_package(
        active,
        ck,
        fallback=str(settings.get("subcategory") or ""),
        aliases=aliases,
    )

    if _is_stocks_package(ck):
        if not bundle.entities:
            return PipelineResult(
                success=False,
                message="No stocks in the selected watchlist. Check stock inputs.",
                parser_warnings=warnings,
            )
        return _run_stocks_pipeline(
            settings=settings,
            category_key=ck,
            bundle=bundle,
            templates=active,
            subcategory=subcategory,
            warnings=warnings,
        )

    if _is_content_template_set(active):
        if not bundle.entities:
            return PipelineResult(
                success=False,
                message="No content entities in the selected input. Check content inputs.",
                parser_warnings=warnings,
            )
        return _run_content_pipeline(
            settings=settings,
            category_key=ck,
            bundle=bundle,
            templates=active,
            subcategory=subcategory,
            warnings=warnings,
        )

    if not bundle.events:
        return PipelineResult(
            success=False,
            message="No content units in the selected date range. Check schedule inputs and date_filter.",
            parser_warnings=warnings,
        )

    try:
        items = build_prompt_items(bundle, active, settings)
    except (TypeError, ValueError) as exc:
        return _client_failure(f"Generation settings error: {exc}", warnings)
    if not items:
        return PipelineResult(
            success=False,
            message="No prompt items to generate (check templates and player stats).",
            parser_warnings=warnings,
        )

    max_q = _max_generated_questions(settings)
    if max_q is not None:
        items = items[:max_q]

    if not items:
        return PipelineResult(
            success=False,
            message="max_generated_questions reduced the work list to zero — increase the limit or enable more templates.",
            parser_warnings=warnings,
        )

    resolve_topic_import_id(settings, ck)

    api_key = settings.get("openai_api_key", "")
    if not api_key:
        return PipelineResult(
            success=False,
            message="OpenAI API key is not set. Add OPENAI_API_KEY to the environment or settings.",
            parser_warnings=warnings,
        )

    try:
        batch_size = int(settings.get("batch_size", 100))
    except (TypeError, ValueError):
        return _client_failure(
            f"Invalid batch_size: {settings.get('batch_size')!r}. Use a positive integer.",
            warnings,
        )
    batches = _chunk_items(items, batch_size)
    total_batches = len(batches)

    prog("Starting generation", 0, total_batches)

    executor = BatchExecutor(settings, prompt_builder=PromptBuilder())

    def on_batch_done(batch_index: int, n_batches: int) -> None:
        prog(f"API batch {batch_index}/{n_batches}", batch_index, n_batches)

    batch_result = executor.execute(items, on_batch_done=on_batch_done)

    if not batch_result.questions:
        return PipelineResult(
            success=False,
            message=_format_generation_failure_message(batch_result),
            batch_result=batch_result,
            parser_warnings=warnings,
        )

    successful_items = _successful_prompt_items(items, batch_result, batch_size)
    assembler = RowAssembler(settings, category_key=ck)
    rows = assembler.assemble_batch(batch_result.questions, successful_items)

    prog("Validating and deduplicating", total_batches, total_batches)

    validation = validate_rows(rows)
    dedup_input = validation.valid_rows
    dedup = deduplicate(dedup_input)

    date_filter = settings.get("date_filter", {})
    try:
        out_path = write_generated_csv_auto(
            dedup.clean_rows,
            subcategory=subcategory,
            date_filter=date_filter,
            output_dir=DEFAULT_OUTPUT_DIR,
        )
    except KeyError as exc:
        return PipelineResult(
            success=False,
            message=f"Output configuration error: missing date_filter field {exc}.",
            batch_result=batch_result,
            validation=validation,
            parser_warnings=warnings,
        )
    except OSError as exc:
        return PipelineResult(
            success=False,
            message=f"Could not write output CSV: {exc}",
            batch_result=batch_result,
            validation=validation,
            parser_warnings=warnings,
        )

    errors_path: Path | None = None
    if validation.invalid_rows:
        errors_path = write_errors_csv(
            validation.invalid_rows,
            output_path=DEFAULT_OUTPUT_DIR / "errors.csv",
        )

    flagged_path: Path | None = None
    if dedup.flagged_rows:
        flagged_path = write_flagged_csv(
            dedup.flagged_rows,
            dedup.flagged_pairs,
            output_path=DEFAULT_OUTPUT_DIR / "flagged.csv",
        )

    qa = build_qa_summary(validation, dedup, batch_result.cost_summary)

    return PipelineResult(
        success=True,
        message=None,
        output_csv=out_path,
        errors_csv=errors_path,
        flagged_csv=flagged_path,
        qa_summary=qa,
        batch_result=batch_result,
        validation=validation,
        parser_warnings=warnings,
    )


def qa_summary_to_dict(summary: QASummary) -> dict[str, Any]:
    return {
        "total_rows_generated": summary.total_rows_generated,
        "rows_passed_validation": summary.rows_passed_validation,
        "rows_failed_validation": summary.rows_failed_validation,
        "rows_flagged_near_duplicate": summary.rows_flagged_near_duplicate,
        "exact_duplicates_removed": summary.exact_duplicates_removed,
        "estimated_cost_usd": summary.estimated_cost_usd,
        "has_cost": summary.has_cost,
    }


def pipeline_result_to_job_dict(result: PipelineResult) -> dict[str, Any]:
    """JSON-serializable job completion payload."""

    payload: dict[str, Any] = {
        "success": result.success,
        "message": result.message,
        "output_csv": result.output_csv.name if result.output_csv else None,
        "errors_csv": result.errors_csv.name if result.errors_csv else None,
        "flagged_csv": result.flagged_csv.name if result.flagged_csv else None,
        "parser_warnings": result.parser_warnings,
    }
    if result.qa_summary:
        payload["qa_summary"] = qa_summary_to_dict(result.qa_summary)
        payload["rows_failed_validation"] = result.qa_summary.rows_failed_validation
    if result.batch_result:
        payload["failed_batches"] = len(result.batch_result.failed_batches)
        payload["total_questions"] = result.batch_result.total_questions
    return payload
