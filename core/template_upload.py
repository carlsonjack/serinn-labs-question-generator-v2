"""Helpers for parsing uploaded template files."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


_GAME_PLACEHOLDER_RE = re.compile(
    r"\{home_team\}|\{away_team\}|\[HOME_TEAM\]|\[AWAY_TEAM\]",
    re.IGNORECASE,
)


def _question_has_game_placeholders(question: str) -> bool:
    return bool(_GAME_PLACEHOLDER_RE.search(question or ""))


def _infer_generation_scope(
    *,
    family: str,
    question: str,
    finalized_opts: str,
    explicit_scope: str,
) -> str:
    if explicit_scope:
        return explicit_scope
    opts = finalized_opts.strip()
    if opts in ("{schedule_teams}", "{team_options}"):
        return "season"
    if family == "entity_stat" and (
        opts == "{entity_options}" or (family == "entity_stat" and not opts)
    ):
        if not _question_has_game_placeholders(question):
            return "season"
    return ""


def parse_uploaded_template_file(name: str, raw_bytes: bytes | str) -> list[dict[str, Any]]:
    """Return one or more template dicts from an uploaded JSON, CSV, or Excel file."""

    suffix = Path(name or "").suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if isinstance(raw_bytes, str):
            raise ValueError("Excel template uploads must be provided as bytes.")
        table_text = _excel_table_to_csv_text(raw_bytes)
        if _looks_like_stock_template_table(table_text):
            return parse_stock_template_table(table_text)
        if _looks_like_content_template_table(table_text):
            return parse_content_template_table(table_text)
        return parse_template_csv_blocks(table_text)

    if isinstance(raw_bytes, bytes):
        text = raw_bytes.decode("utf-8-sig")
    else:
        text = raw_bytes

    if suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Root JSON value must be an object")
        return [data]

    if suffix == ".csv":
        if _looks_like_stock_template_table(text):
            return parse_stock_template_table(text)
        if _looks_like_content_template_table(text):
            return parse_content_template_table(text)
        return parse_template_csv_blocks(text)

    raise ValueError("Only .json, .csv, .xlsx, and .xls template files are accepted.")


def _excel_table_to_csv_text(raw_bytes: bytes) -> str:
    frame = pd.read_excel(io.BytesIO(raw_bytes), dtype=str).fillna("")
    out = io.StringIO()
    frame.to_csv(out, index=False)
    return out.getvalue()


def _raw_table_header_cells(text: str) -> list[str]:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in row)]
    if not rows:
        return []
    return [str(c or "").strip() for c in rows[0]]


def _snake_case_repo_template_headers(raw_headers: list[str]) -> bool:
    """Detect ``template_id``-style exports; those must not use the client stock (PascalCase) parser.

    ``Template ID`` normalizes to the same logical key as ``template_id``, but the former has a
    space in the raw header (client stock layout). Repo-style columns use underscores and no
    spaces in those cells.
    """

    by_norm: dict[str, str] = {}
    for h in raw_headers:
        hs = str(h or "").strip()
        if not hs:
            continue
        key = hs.lower().replace("-", "_").replace(" ", "_")
        by_norm[key] = hs
    required = ("template_id", "question_template", "answer_type")
    if not all(k in by_norm for k in required):
        return False
    return all(" " not in by_norm[k] for k in required)


def _looks_like_stock_template_table(text: str) -> bool:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in row)]
    if not rows:
        return False
    if _snake_case_repo_template_headers(_raw_table_header_cells(text)):
        return False
    headers = {_normalize_table_header(h) for h in rows[0]}
    if "template type" in headers or "required dataset fields" in headers:
        return False
    return {"template id", "question template", "answer type"} <= headers


def _wide_template_header_keys(text: str) -> set[str]:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in row)]
    if not rows:
        return set()
    return {_normalize_table_header(h) for h in rows[0]}


def _looks_like_content_template_table(text: str) -> bool:
    """Detect one-header-row template tables (Excel/CSV Layout A).

    Accepts common column aliases used in repo docs and LLM-authored sheets
    (e.g. ``question`` vs ``question_template``, ``id`` vs ``template_id``).
    """

    headers = _wide_template_header_keys(text)
    if not headers:
        return False
    has_id = "template id" in headers or "id" in headers
    has_question = "question template" in headers or "question" in headers
    has_answer_type = "answer type" in headers
    return has_id and has_question and has_answer_type


def _normalize_table_header(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def parse_stock_template_table(text: str) -> list[dict[str, Any]]:
    """Parse the client's stock template CSV into repo-native template dicts."""

    reader = csv.DictReader(io.StringIO(text))
    templates: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(str(value or "").strip() for value in row.values()):
            continue
        template_id = str(row.get("Template ID") or "").strip()
        question = str(row.get("Question Template") or "").strip()
        answer_type = str(row.get("Answer Type") or "").strip()
        if not template_id or not question or not answer_type:
            raise ValueError(f"Stock template row {row_number} is missing required fields.")
        templates.append(
            {
                "id": template_id,
                "subcategory": "stocks",
                "question_family": "stock",
                "question": question,
                "answer_type": answer_type,
                "answer_options": str(row.get("Answer Options") or "").strip(),
                "priority": _coerce_stock_priority(row.get("Recommended Priority")),
                "requires_entities": False,
                "timeframe": str(row.get("Timeframe") or "").strip(),
                "template_name": str(row.get("Template Name") or "").strip(),
                "notes": str(row.get("Notes") or "").strip(),
            }
        )
    if not templates:
        raise ValueError("Stock template CSV contains no templates.")
    return templates


def _parse_optional_bool(raw: Any) -> bool | None:
    """Parse spreadsheet booleans; return ``None`` when the cell is blank."""

    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if low in {"true", "1", "yes", "y"}:
        return True
    if low in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"requires_entities must be a boolean value, not {raw!r}")


def _finalize_wide_answer_options(
    answer_type: str,
    answer_options: str,
    question_family: str,
) -> str:
    """Apply defaults so wide-table uploads satisfy :func:`parse_template_dict` rules."""

    ao = (answer_options or "").strip()
    if answer_type == "yes_no":
        if not ao:
            if question_family in {"event", "entity_stat"}:
                return "Yes||No"
            return ""
        return ao
    if answer_type == "multiple_choice" and question_family == "entity_stat" and not ao:
        return "{entity_options}"
    return ao


def _resolve_wide_requires_entities(
    question_family: str,
    cell: bool | None,
    *,
    row_number: int,
) -> bool:
    if question_family == "entity_stat":
        if cell is False:
            raise ValueError(
                f"Content template row {row_number}: question_family 'entity_stat' "
                "requires requires_entities true (or omit the column)."
            )
        return True
    if cell is True:
        raise ValueError(
            f"Content template row {row_number}: requires_entities true is only valid when "
            "question_family is 'entity_stat'."
        )
    return False


def _normalize_upload_answer_type(raw: str, answer_options: str) -> str:
    """Map spreadsheet synonyms to schema ``answer_type`` values."""

    s = (raw or "").strip().lower()
    opts = (answer_options or "").strip()
    if s in ("single_select", "single choice", "single-choice", "pick_one"):
        return "multiple_choice"
    if s in ("binary", "boolean", "yn", "y/n"):
        if opts and opts != "Yes||No" and "||" in opts:
            return "multiple_choice"
        return "yes_no"
    return str(raw or "").strip()


def parse_content_template_table(text: str) -> list[dict[str, Any]]:
    """Parse generic template tables (content, event, entity_stat, etc.) from CSV/Excel exports.

    Recognized columns beyond the core ``template_id`` / ``question_template`` / ``answer_type``
    set include ``question_family``, ``requires_entities``, ``stat_column``, ``top_n_per_team``
    (alias ``top_n``), and date-rule strings. ``question_family`` may be omitted when
    ``stat_column`` is set — the row is then treated as ``entity_stat``.
    """

    reader = csv.DictReader(io.StringIO(text))
    templates: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(str(value or "").strip() for value in row.values()):
            continue
        template_id = str(row.get("template_id") or row.get("id") or "").strip()
        question = str(row.get("question_template") or row.get("question") or "").strip()
        answer_opts = (
            str(row.get("answer_options_pattern") or "").strip()
            or str(row.get("answer_options_rule") or "").strip()
            or str(row.get("answer_options") or "").strip()
        )
        answer_type_raw = str(row.get("answer_type") or "").strip()
        answer_type = _normalize_upload_answer_type(answer_type_raw, answer_opts)
        subcategory = str(row.get("subcategory") or "").strip() or "Content"
        if not template_id or not question or not answer_type:
            raise ValueError(f"Content template row {row_number} is missing required fields.")
        priority_raw = row.get("default_priority")
        if priority_raw is None or str(priority_raw).strip() == "":
            priority_raw = row.get("priority")
        family_raw = str(row.get("question_family") or "").strip().lower()
        if family_raw:
            family = family_raw
        elif str(row.get("stat_column") or "").strip():
            family = "entity_stat"
        else:
            rules_blob = " ".join(
                str(row.get(k) or "")
                for k in (
                    "start_date_rule",
                    "expiration_date_rule",
                    "resolution_date_rule",
                    "required_input_file",
                )
            ).lower()
            ql = question.lower()
            opts_stripped = answer_opts.strip()
            named_mc_token = (
                bool(opts_stripped)
                and "||" not in answer_opts
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", opts_stripped) is not None
            )
            if (
                "event" in rules_blob
                or "{home_team}" in ql
                or "{away_team}" in ql
                or named_mc_token
            ):
                family = "event"
            else:
                family = "content"
        if family not in {"content", "event", "entity_stat", "stock"}:
            raise ValueError(
                f"Content template row {row_number}: invalid question_family {family!r} "
                "(expected content, event, entity_stat, or stock)."
            )

        req_cell = _parse_optional_bool(row.get("requires_entities"))
        requires_entities = _resolve_wide_requires_entities(family, req_cell, row_number=row_number)
        finalized_opts = _finalize_wide_answer_options(answer_type, answer_opts, family)

        scope_raw = str(row.get("generation_scope") or "").strip().lower()
        scope_raw = _infer_generation_scope(
            family=family,
            question=question,
            finalized_opts=finalized_opts,
            explicit_scope=scope_raw,
        )

        rec: dict[str, Any] = {
            "id": template_id,
            "subcategory": subcategory,
            "question_family": family,
            "question": question,
            "answer_type": answer_type,
            "answer_options": finalized_opts,
            "priority": _coerce_stock_priority(priority_raw),
            "requires_entities": requires_entities,
            "template_type": str(row.get("template_type") or "").strip(),
            "required_dataset_fields": str(row.get("required_dataset_fields") or "").strip(),
            "notes": str(row.get("notes") or "").strip(),
            "resolution_date_rule": str(row.get("resolution_date_rule") or "").strip(),
            "start_date_rule": str(row.get("start_date_rule") or "").strip(),
            "expiration_date_rule": str(row.get("expiration_date_rule") or "").strip(),
        }
        if scope_raw:
            rec["generation_scope"] = scope_raw
        if family == "entity_stat":
            stat_column = str(row.get("stat_column") or "").strip()
            if not stat_column:
                raise ValueError(
                    f"Content template row {row_number}: question_family 'entity_stat' "
                    "requires a non-empty stat_column (e.g. PTS, HR)."
                )
            rec["stat_column"] = stat_column
            top_raw = row.get("top_n_per_team")
            if top_raw is None or str(top_raw).strip() == "":
                top_raw = row.get("top_n")
            if top_raw is None or str(top_raw).strip() == "":
                rec["top_n_per_team"] = 20 if scope_raw == "season" else 2
            else:
                rec["top_n_per_team"] = _parse_int(str(top_raw).strip(), "top_n_per_team")
        elif family == "stock":
            rec["subcategory"] = "stocks"
            timeframe = str(row.get("timeframe") or row.get("Timeframe") or "").strip()
            if timeframe:
                rec["timeframe"] = timeframe
            template_name = str(row.get("template_name") or row.get("Template Name") or "").strip()
            if template_name:
                rec["template_name"] = template_name
            for date_key in (
                "start_date_rule",
                "expiration_date_rule",
                "resolution_date_rule",
            ):
                rec.pop(date_key, None)

        templates.append(rec)
    if not templates:
        raise ValueError("Content template CSV contains no templates.")
    return templates


def _coerce_stock_priority(value: Any) -> int | str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return _parse_int(raw, "Recommended Priority")


def parse_template_csv_blocks(text: str) -> list[dict[str, Any]]:
    """Parse repeated 2-row CSV blocks into template dicts."""

    rows = [
        row
        for row in csv.reader(io.StringIO(text))
        if any(str(cell).strip() for cell in row)
    ]
    if not rows:
        raise ValueError("CSV file is empty.")
    if len(rows) % 2 != 0:
        hint = ""
        if _looks_like_content_template_table(text):
            hint = (
                " This file looks like a one-row-per-template table (Layout A). "
                "Use a single header row with columns such as template_id, question, "
                "and answer_type — not alternating two-row blocks."
            )
        else:
            headers = _wide_template_header_keys(text)
            if headers and ("template id" in headers or "id" in headers):
                hint = (
                    " If you meant a spreadsheet with one row per template, include "
                    "question or question_template and answer_type in the header row."
                )
        raise ValueError(
            "CSV file must contain header/value row pairs (an even number of non-empty rows)."
            + hint
        )

    templates: list[dict[str, Any]] = []
    for idx in range(0, len(rows), 2):
        headers = rows[idx]
        values = rows[idx + 1]
        block_num = idx // 2 + 1
        if len(headers) != len(values):
            raise ValueError(
                f"CSV block {block_num} has {len(headers)} header cells but {len(values)} value cells."
            )
        data: dict[str, Any] = {}
        seen_headers: set[str] = set()
        for col_idx, (raw_key, raw_value) in enumerate(zip(headers, values), start=1):
            key = str(raw_key).strip()
            if not key:
                raise ValueError(
                    f"CSV block {block_num} has an empty field name in column {col_idx}."
                )
            if key in seen_headers:
                raise ValueError(
                    f"CSV block {block_num} repeats field {key!r}."
                )
            seen_headers.add(key)
            coerced = _coerce_csv_value(key, raw_value)
            if coerced is _SKIP_FIELD:
                continue
            data[key] = coerced
        if not data:
            raise ValueError(f"CSV block {block_num} is empty.")
        templates.append(data)
    return templates


_SKIP_FIELD = object()


def _coerce_csv_value(key: str, value: Any) -> Any:
    raw = str(value).strip()
    if raw == "":
        if key in {"line", "top_n_per_team", "stat_column", "_comment"}:
            return _SKIP_FIELD
        return ""
    if key == "requires_entities":
        return _parse_bool(raw, key)
    if key == "top_n_per_team":
        return _parse_int(raw, key)
    if key == "line":
        return _parse_float(raw, key)
    if key == "priority":
        return _parse_int(raw, key)
    return raw


def _parse_bool(raw: str, key: str) -> bool:
    value = raw.strip().lower()
    if value in {"true", "1", "yes", "y"}:
        return True
    if value in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"{key} must be a boolean value.")


def _parse_int(raw: str, key: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer value.") from exc


def _parse_float(raw: str, key: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a numeric value.") from exc
