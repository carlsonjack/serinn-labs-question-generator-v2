"""Question template records loaded from JSON (EPIC 3)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from core.resolution_date_spec import parse_resolution_date_spec_dict

ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "subcategory",
        "question_family",
        "question",
        "answer_type",
        "answer_options",
        "priority",
        "requires_entities",
        "stat_column",
        "top_n_per_team",
        "line",
        "timeframe",
        "template_type",
        "required_dataset_fields",
        "placeholder_mappings",
        "generation_strategy",
        "entity_count",
        "template_name",
        "notes",
        "_comment",
        "resolution_date_rule",
        "resolution_date_spec",
        "start_date_rule",
        "start_date_spec",
        "expiration_date_rule",
        "expiration_date_spec",
        "generation_scope",
    }
)

QUESTION_FAMILIES: frozenset[str] = frozenset({"event", "entity_stat", "stock", "content"})
GENERATION_SCOPES: frozenset[str] = frozenset({"event", "season"})
ANSWER_TYPES: frozenset[str] = frozenset({"yes_no", "multiple_choice"})


@dataclass(frozen=True)
class QuestionTemplate:
    """One row from templates/*.json after validation."""

    id: str
    subcategory: str
    question_family: str
    question: str
    answer_type: str
    answer_options: str
    priority: int | str
    requires_entities: bool
    stat_column: str | None = None
    top_n_per_team: int | None = None
    line: float | None = None
    timeframe: str | None = None
    template_type: str | None = None
    required_dataset_fields: str | None = None
    placeholder_mappings: dict[str, Any] | None = None
    generation_strategy: str | None = None
    entity_count: int | None = None
    template_name: str | None = None
    notes: str | None = None
    _comment: str | None = None
    resolution_date_rule: str | None = None
    resolution_date_spec: dict[str, Any] | None = None
    start_date_rule: str | None = None
    start_date_spec: dict[str, Any] | None = None
    expiration_date_rule: str | None = None
    expiration_date_spec: dict[str, Any] | None = None
    generation_scope: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for tests and downstream JSON-friendly consumers."""

        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None or k == "_comment"}


def parse_template_dict(data: dict[str, Any]) -> QuestionTemplate:
    """Validate raw JSON object and return a QuestionTemplate."""

    unknown = set(data.keys()) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"Unknown keys: {sorted(unknown)}")

    missing = [k for k in ("id", "subcategory", "question_family", "question", "answer_type", "priority") if k not in data]
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    if "requires_entities" not in data:
        raise ValueError("Missing required key: requires_entities")

    qid = _str_field(data, "id")
    subcategory = _str_field(data, "subcategory")
    question_family = _str_field(data, "question_family")
    question = _str_field(data, "question")
    answer_type = _str_field(data, "answer_type")
    priority = _priority_field(data, "priority")

    if question_family not in QUESTION_FAMILIES:
        raise ValueError(f"Invalid question_family: {question_family!r}")
    if answer_type not in ANSWER_TYPES:
        raise ValueError(f"Invalid answer_type: {answer_type!r}")
    requires_entities = data["requires_entities"]
    if not isinstance(requires_entities, bool):
        raise ValueError("requires_entities must be a boolean")

    answer_options = _optional_str_field(data, "answer_options")

    stat_column = data.get("stat_column")
    top_raw = data.get("top_n_per_team")
    line_raw = data.get("line")
    timeframe = data.get("timeframe")
    template_type = data.get("template_type")
    required_dataset_fields = data.get("required_dataset_fields")
    placeholder_mappings = data.get("placeholder_mappings")
    generation_strategy = data.get("generation_strategy")
    entity_count_raw = data.get("entity_count")
    template_name = data.get("template_name")
    notes = data.get("notes")
    comment = data.get("_comment")
    resolution_date_rule = data.get("resolution_date_rule")
    resolution_date_spec_raw = data.get("resolution_date_spec")
    start_date_rule = data.get("start_date_rule")
    start_date_spec_raw = data.get("start_date_spec")
    expiration_date_rule = data.get("expiration_date_rule")
    expiration_date_spec_raw = data.get("expiration_date_spec")
    generation_scope_raw = data.get("generation_scope")

    if stat_column is not None and not isinstance(stat_column, str):
        raise ValueError("stat_column must be a string or omitted")
    if top_raw is not None:
        if isinstance(top_raw, bool) or not isinstance(top_raw, (int, float)):
            raise ValueError("top_n_per_team must be an integer or omitted")
        if isinstance(top_raw, float) and not top_raw.is_integer():
            raise ValueError("top_n_per_team must be a whole number")
    if line_raw is not None and not isinstance(line_raw, (int, float)):
        raise ValueError("line must be a number or omitted")
    if comment is not None and not isinstance(comment, str):
        raise ValueError("_comment must be a string or omitted")
    if timeframe is not None and not isinstance(timeframe, str):
        raise ValueError("timeframe must be a string or omitted")
    if template_type is not None and not isinstance(template_type, str):
        raise ValueError("template_type must be a string or omitted")
    if required_dataset_fields is not None and not isinstance(required_dataset_fields, str):
        raise ValueError("required_dataset_fields must be a string or omitted")
    if placeholder_mappings is not None and not isinstance(placeholder_mappings, dict):
        raise ValueError("placeholder_mappings must be an object or omitted")
    if generation_strategy is not None and not isinstance(generation_strategy, str):
        raise ValueError("generation_strategy must be a string or omitted")
    if entity_count_raw is not None:
        if isinstance(entity_count_raw, bool) or not isinstance(entity_count_raw, (int, float)):
            raise ValueError("entity_count must be an integer or omitted")
        if isinstance(entity_count_raw, float) and not entity_count_raw.is_integer():
            raise ValueError("entity_count must be a whole number")
    if template_name is not None and not isinstance(template_name, str):
        raise ValueError("template_name must be a string or omitted")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string or omitted")
    if resolution_date_rule is not None and not isinstance(resolution_date_rule, str):
        raise ValueError("resolution_date_rule must be a string or omitted")
    if start_date_rule is not None and not isinstance(start_date_rule, str):
        raise ValueError("start_date_rule must be a string or omitted")
    if expiration_date_rule is not None and not isinstance(expiration_date_rule, str):
        raise ValueError("expiration_date_rule must be a string or omitted")
    if generation_scope_raw is not None and not isinstance(generation_scope_raw, str):
        raise ValueError("generation_scope must be a string or omitted")
    generation_scope_str = (
        generation_scope_raw.strip().lower() if generation_scope_raw else None
    )
    if generation_scope_str and generation_scope_str not in GENERATION_SCOPES:
        raise ValueError(
            f"Invalid generation_scope: {generation_scope_raw!r} "
            f"(expected one of {sorted(GENERATION_SCOPES)})"
        )
    resolution_date_rule_str = resolution_date_rule.strip() if resolution_date_rule else None
    start_date_rule_str = start_date_rule.strip() if start_date_rule else None
    expiration_date_rule_str = expiration_date_rule.strip() if expiration_date_rule else None
    resolution_date_spec: dict[str, Any] | None = None
    if resolution_date_spec_raw is not None:
        if not isinstance(resolution_date_spec_raw, dict):
            raise ValueError("resolution_date_spec must be an object or omitted")
        resolution_date_spec = parse_resolution_date_spec_dict(resolution_date_spec_raw).model_dump(
            mode="json"
        )
    start_date_spec: dict[str, Any] | None = None
    if start_date_spec_raw is not None:
        if not isinstance(start_date_spec_raw, dict):
            raise ValueError("start_date_spec must be an object or omitted")
        start_date_spec = parse_resolution_date_spec_dict(start_date_spec_raw).model_dump(mode="json")
    expiration_date_spec: dict[str, Any] | None = None
    if expiration_date_spec_raw is not None:
        if not isinstance(expiration_date_spec_raw, dict):
            raise ValueError("expiration_date_spec must be an object or omitted")
        expiration_date_spec = parse_resolution_date_spec_dict(expiration_date_spec_raw).model_dump(
            mode="json"
        )

    line: float | None = float(line_raw) if line_raw is not None else None
    entity_count = int(entity_count_raw) if entity_count_raw is not None else None
    if entity_count is not None and entity_count < 1:
        raise ValueError("entity_count must be >= 1")

    if question_family == "entity_stat":
        if line_raw is not None:
            raise ValueError("entity_stat templates must not set line")
        if not requires_entities:
            raise ValueError("entity_stat templates must set requires_entities to true")
        if not stat_column or not stat_column.strip():
            raise ValueError("entity_stat templates require stat_column")
        if top_raw is None or int(top_raw) < 1:
            raise ValueError("entity_stat templates require top_n_per_team >= 1")
        top_n = int(top_raw)
    elif question_family == "event":
        if requires_entities:
            raise ValueError("event templates must set requires_entities to false")
        if stat_column is not None or top_raw is not None:
            raise ValueError("event templates must not set stat_column or top_n_per_team")
        top_n = None
    elif question_family == "stock":
        if requires_entities:
            raise ValueError("stock templates must set requires_entities to false")
        if stat_column is not None or top_raw is not None:
            raise ValueError("stock templates must not set stat_column or top_n_per_team")
        top_n = None
    else:
        if requires_entities:
            raise ValueError("content templates must set requires_entities to false")
        if stat_column is not None or top_raw is not None:
            raise ValueError("content templates must not set stat_column or top_n_per_team")
        top_n = None

    _validate_generation_scope(
        generation_scope_str,
        question_family,
        answer_options,
        requires_entities,
    )

    _validate_answer_options(answer_type, answer_options, requires_entities, question_family)

    return QuestionTemplate(
        id=qid,
        subcategory=subcategory,
        question_family=question_family,
        question=question,
        answer_type=answer_type,
        answer_options=answer_options,
        priority=priority,
        requires_entities=requires_entities,
        stat_column=stat_column.strip() if stat_column else None,
        top_n_per_team=top_n,
        line=line,
        timeframe=timeframe.strip() if timeframe else None,
        template_type=template_type.strip() if template_type else None,
        required_dataset_fields=required_dataset_fields.strip() if required_dataset_fields else None,
        placeholder_mappings=placeholder_mappings,
        generation_strategy=generation_strategy.strip() if generation_strategy else None,
        entity_count=entity_count,
        template_name=template_name.strip() if template_name else None,
        notes=notes.strip() if notes else None,
        _comment=comment,
        resolution_date_rule=resolution_date_rule_str or None,
        resolution_date_spec=resolution_date_spec,
        start_date_rule=start_date_rule_str or None,
        start_date_spec=start_date_spec,
        expiration_date_rule=expiration_date_rule_str or None,
        expiration_date_spec=expiration_date_spec,
        generation_scope=generation_scope_str or None,
    )


def _str_field(data: dict[str, Any], key: str) -> str:
    if key not in data:
        raise ValueError(f"Missing required key: {key}")
    val = data[key]
    if not isinstance(val, str):
        raise ValueError(f"{key} must be a string")
    if not val.strip():
        raise ValueError(f"{key} must be non-empty")
    return val


def _optional_str_field(data: dict[str, Any], key: str) -> str:
    if key not in data:
        raise ValueError(f"Missing required key: {key}")
    val = data[key]
    if not isinstance(val, str):
        raise ValueError(f"{key} must be a string")
    return val.strip()


def _priority_field(data: dict[str, Any], key: str) -> int | str:
    if key not in data:
        raise ValueError(f"Missing required key: {key}")
    val = data[key]
    if val == "":
        return ""
    if isinstance(val, bool):
        raise ValueError("priority must be an integer or blank")
    if isinstance(val, int):
        if val < 0:
            raise ValueError("priority must be a non-negative integer or blank")
        return val
    raise ValueError("priority must be an integer or blank")


def _uses_schedule_teams_placeholder(answer_options: str) -> bool:
    return (answer_options or "").strip() in ("{schedule_teams}", "{team_options}")


def _validate_generation_scope(
    generation_scope: str | None,
    question_family: str,
    answer_options: str,
    requires_entities: bool,
) -> None:
    if generation_scope != "season":
        return
    if question_family in {"content", "stock"}:
        raise ValueError(
            "generation_scope=season is only valid for sports event or entity_stat templates"
        )
    if _uses_schedule_teams_placeholder(answer_options):
        if question_family != "event":
            raise ValueError(
                "season templates with {schedule_teams} must use question_family=event"
            )
        if requires_entities:
            raise ValueError(
                "season templates with {schedule_teams} must set requires_entities to false"
            )
    elif requires_entities:
        if question_family != "entity_stat":
            raise ValueError(
                "season templates with {entity_options} must use question_family=entity_stat"
            )


def _validate_answer_options(
    answer_type: str,
    answer_options: str,
    requires_entities: bool,
    question_family: str,
) -> None:
    if answer_type == "yes_no":
        if question_family in {"stock", "content"} and answer_options == "":
            return
        if answer_options != "Yes||No":
            raise ValueError("yes_no templates must use answer_options: \"Yes||No\"")
        return
    if answer_type == "multiple_choice":
        if requires_entities:
            return
        if "||" in answer_options:
            return
        ao = (answer_options or "").strip()
        if ao in ("{schedule_teams}", "{team_options}"):
            return
        if question_family == "event" and ao and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", ao):
            return
        raise ValueError("multiple_choice event templates must use || in answer_options")
    raise AssertionError("unreachable")
