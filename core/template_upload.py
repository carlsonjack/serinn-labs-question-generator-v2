"""Helpers for parsing uploaded template files."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd


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


def _looks_like_stock_template_table(text: str) -> bool:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in row)]
    if not rows:
        return False
    headers = {_normalize_table_header(h) for h in rows[0]}
    if "template type" in headers or "required dataset fields" in headers:
        return False
    return {"template id", "question template", "answer type"} <= headers


def _looks_like_content_template_table(text: str) -> bool:
    rows = [row for row in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in row)]
    if not rows:
        return False
    headers = {_normalize_table_header(h) for h in rows[0]}
    return {"template id", "question template", "answer type"} <= headers


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


def parse_content_template_table(text: str) -> list[dict[str, Any]]:
    """Parse generic content/entertainment template tables into native templates."""

    reader = csv.DictReader(io.StringIO(text))
    templates: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(str(value or "").strip() for value in row.values()):
            continue
        template_id = str(row.get("template_id") or "").strip()
        question = str(row.get("question_template") or "").strip()
        answer_type = str(row.get("answer_type") or "").strip()
        subcategory = str(row.get("subcategory") or "").strip() or "Content"
        if not template_id or not question or not answer_type:
            raise ValueError(f"Content template row {row_number} is missing required fields.")
        templates.append(
            {
                "id": template_id,
                "subcategory": subcategory,
                "question_family": "content",
                "question": question,
                "answer_type": answer_type,
                "answer_options": str(row.get("answer_options_pattern") or "").strip(),
                "priority": _coerce_stock_priority(row.get("default_priority")),
                "requires_entities": False,
                "template_type": str(row.get("template_type") or "").strip(),
                "required_dataset_fields": str(row.get("required_dataset_fields") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "resolution_date_rule": str(row.get("resolution_date_rule") or "").strip(),
            }
        )
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
        raise ValueError(
            "CSV file must contain header/value row pairs (an even number of non-empty rows)."
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
