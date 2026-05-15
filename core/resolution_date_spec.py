"""Compile and evaluate per-template resolution date rules (non-stock).

Natural-language ``resolution_date_rule`` strings are converted to a structured
``ResolutionDateSpec`` at template upload: common phrases are inferred locally,
then OpenAI fills in the rest. Generation evaluates the spec deterministically
without calling the API.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from openai import BadRequestError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.date_coercion import parse_entity_calendar_date
from core.date_rules import parse_event_datetime

logger = logging.getLogger(__name__)

ResolutionKind = Literal[
    "offset_from_anchor",
    "calendar_in_year",
    "metadata_date",
    "window_end",
    "none",
]

ContentAnchor = Literal[
    "release_date",
    "question_start",
    "question_expiration",
    "metadata_field",
]

EventAnchor = Literal[
    "event_datetime",
    "question_start",
    "question_expiration",
    "metadata_field",
]

YearPolicy = Literal[
    "release_year",
    "release_year_plus_1",
    "event_year",
    "event_year_plus_1",
    "static_context_year",
]


class ResolutionDateSpec(BaseModel):
    """Structured resolution rule produced by upload-time AI compile."""

    model_config = ConfigDict(extra="forbid")

    kind: ResolutionKind
    anchor: Optional[str] = None
    metadata_key: Optional[str] = None
    offset_days: int = 0
    offset_hours: int = 0
    calendar_month: Optional[int] = Field(default=None, ge=1, le=12)
    calendar_day: Optional[int] = Field(default=None, ge=1, le=31)
    year_policy: Optional[YearPolicy] = None
    end_offset_days: Optional[int] = None

    @model_validator(mode="after")
    def _consistency(self) -> ResolutionDateSpec:
        if self.kind == "offset_from_anchor":
            if not self.anchor:
                raise ValueError("offset_from_anchor requires anchor")
            if self.anchor == "metadata_field" and not (self.metadata_key or "").strip():
                raise ValueError("metadata_field anchor requires metadata_key")
        elif self.kind == "calendar_in_year":
            if self.calendar_month is None or self.calendar_day is None:
                raise ValueError("calendar_in_year requires calendar_month and calendar_day")
            if not self.year_policy:
                raise ValueError("calendar_in_year requires year_policy")
        elif self.kind == "metadata_date":
            if not (self.metadata_key or "").strip():
                raise ValueError("metadata_date requires metadata_key")
        elif self.kind == "window_end":
            if not self.anchor:
                raise ValueError("window_end requires anchor")
            if self.end_offset_days is None:
                raise ValueError("window_end requires end_offset_days")
        return self


class _CompiledResolutionItem(BaseModel):
    template_id: str
    spec: ResolutionDateSpec


class _CompiledResolutionBatch(BaseModel):
    items: List[_CompiledResolutionItem]


@dataclass(frozen=True)
class ContentResolutionContext:
    release_date: date
    question_start: date
    question_expiration: date
    metadata: dict[str, Any]
    static_year: Optional[int] = None


@dataclass(frozen=True)
class EventResolutionContext:
    event_datetime: datetime
    question_start: datetime
    question_expiration: datetime
    metadata: dict[str, Any]


def parse_resolution_date_spec_dict(raw: Optional[Dict[str, Any]]) -> Optional[ResolutionDateSpec]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("resolution_date_spec must be an object")
    return ResolutionDateSpec.model_validate(raw)


_START_DATE_PLUS_DAYS = re.compile(
    r"(?i)(start\s*[_\s-]*date|question\s*start)\s*\+\s*(\d+)\s*(?:calendar\s*)?(?:day|days)\b",
)
_EXPIRATION_DATE_PLUS_DAYS = re.compile(
    r"(?i)(expiration\s*[_\s-]*date|question\s*expiration)\s*\+\s*(\d+)\s*(?:calendar\s*)?(?:day|days)\b",
)
_RELEASE_DATE_PLUS_DAYS = re.compile(
    r"(?i)(release\s*[_\s-]*date|opening\s*date)\s*\+\s*(\d+)\s*(?:calendar\s*)?(?:day|days)\b",
)


def _try_infer_resolution_spec_from_rule(
    rule: str, question_family: str
) -> Optional[ResolutionDateSpec]:
    """Map common phrasing to a spec without OpenAI (upload path).

    In this codebase, CSV ``start_date`` for content rows matches
    :attr:`ContentResolutionContext.question_start` (see ``_content_dates``),
    not ``release_date``.
    """

    fam = (question_family or "").strip().lower()
    if fam == "stock":
        return None
    if not (rule or "").strip():
        return None
    m = _START_DATE_PLUS_DAYS.search(rule)
    if m:
        n = int(m.group(2))
        return ResolutionDateSpec(
            kind="offset_from_anchor", anchor="question_start", offset_days=n
        )
    m = _EXPIRATION_DATE_PLUS_DAYS.search(rule)
    if m:
        n = int(m.group(2))
        return ResolutionDateSpec(
            kind="offset_from_anchor", anchor="question_expiration", offset_days=n
        )
    m = _RELEASE_DATE_PLUS_DAYS.search(rule)
    if m:
        n = int(m.group(2))
        if fam == "content":
            anchor = "release_date"
        else:
            anchor = "event_datetime"
        return ResolutionDateSpec(kind="offset_from_anchor", anchor=anchor, offset_days=n)
    return None


def _metadata_date(metadata: Dict[str, Any], key: str) -> Optional[date]:
    raw = metadata.get(key)
    if raw in (None, ""):
        for variant in (key, key.lower(), key.replace("_", " ")):
            raw = metadata.get(variant)
            if raw not in (None, ""):
                break
        else:
            return None
    try:
        parsed = parse_entity_calendar_date(str(raw))
        if isinstance(parsed, datetime):
            return parsed.date()
        return parsed
    except (TypeError, ValueError):
        return None


def _resolve_year_for_calendar(year_policy: YearPolicy, ctx: ContentResolutionContext) -> int:
    y = ctx.release_date.year
    if year_policy == "release_year":
        return y
    if year_policy == "release_year_plus_1":
        return y + 1
    if year_policy == "event_year":
        return y
    if year_policy == "event_year_plus_1":
        return y + 1
    if year_policy == "static_context_year":
        if ctx.static_year is not None:
            return ctx.static_year
        return y
    raise ValueError(f"Unknown year_policy: {year_policy}")


def _resolve_year_for_calendar_event(year_policy: YearPolicy, ctx: EventResolutionContext) -> int:
    y = ctx.event_datetime.year
    if year_policy in ("release_year", "event_year"):
        return y
    if year_policy in ("release_year_plus_1", "event_year_plus_1"):
        return y + 1
    if year_policy == "static_context_year":
        return y
    raise ValueError(f"Unknown year_policy for event: {year_policy}")


def compute_resolution_date_for_content(
    spec: Optional[ResolutionDateSpec],
    ctx: ContentResolutionContext,
) -> Optional[date]:
    """Return calendar resolution date, or None to fall back to legacy heuristics."""

    if spec is None or spec.kind == "none":
        return None

    if spec.kind == "metadata_date":
        d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        return d

    if spec.kind == "calendar_in_year" and spec.year_policy and spec.calendar_month and spec.calendar_day:
        year = _resolve_year_for_calendar(spec.year_policy, ctx)
        return date(year, spec.calendar_month, spec.calendar_day)

    if spec.kind == "window_end":
        anchor = spec.anchor or "release_date"
        base: date | None
        if anchor == "release_date":
            base = ctx.release_date
        elif anchor == "question_start":
            base = ctx.question_start
        elif anchor == "question_expiration":
            base = ctx.question_expiration
        elif anchor == "metadata_field":
            base = _metadata_date(ctx.metadata, spec.metadata_key or "")
        else:
            return None
        if base is None:
            return None
        return base + timedelta(days=int(spec.end_offset_days or 0))

    if spec.kind == "offset_from_anchor":
        anchor = spec.anchor or ""
        base_dt: date | None = None
        if anchor == "release_date":
            base_dt = ctx.release_date
        elif anchor == "question_start":
            base_dt = ctx.question_start
        elif anchor == "question_expiration":
            base_dt = ctx.question_expiration
        elif anchor == "metadata_field":
            base_dt = _metadata_date(ctx.metadata, spec.metadata_key or "")
        else:
            return None
        if base_dt is None:
            return None
        out = datetime.combine(base_dt, datetime.min.time()) + timedelta(
            days=spec.offset_days,
            hours=spec.offset_hours,
        )
        return out.date()

    return None


def compute_resolution_datetime_for_event(
    spec: Optional[ResolutionDateSpec],
    ctx: EventResolutionContext,
) -> Optional[datetime]:
    """Return naive resolution datetime, or None to keep YAML-derived resolution."""

    if spec is None or spec.kind == "none":
        return None

    if spec.kind == "metadata_date":
        d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        if d is None:
            return None
        return datetime.combine(d, datetime.min.time())

    if spec.kind == "calendar_in_year" and spec.year_policy and spec.calendar_month and spec.calendar_day:
        year = _resolve_year_for_calendar_event(spec.year_policy, ctx)
        d = date(year, spec.calendar_month, spec.calendar_day)
        return datetime.combine(d, datetime.min.time())

    if spec.kind == "window_end":
        anchor = spec.anchor or "event_datetime"
        base: datetime | None
        if anchor == "event_datetime":
            base = ctx.event_datetime
        elif anchor == "question_start":
            base = ctx.question_start
        elif anchor == "question_expiration":
            base = ctx.question_expiration
        elif anchor == "metadata_field":
            d = _metadata_date(ctx.metadata, spec.metadata_key or "")
            base = datetime.combine(d, datetime.min.time()) if d else None
        else:
            return None
        if base is None:
            return None
        return base + timedelta(days=int(spec.end_offset_days or 0))

    if spec.kind == "offset_from_anchor":
        anchor = spec.anchor or "event_datetime"
        base: datetime | None
        if anchor == "event_datetime":
            base = ctx.event_datetime
        elif anchor == "question_start":
            base = ctx.question_start
        elif anchor == "question_expiration":
            base = ctx.question_expiration
        elif anchor == "metadata_field":
            d = _metadata_date(ctx.metadata, spec.metadata_key or "")
            base = datetime.combine(d, datetime.min.time()) if d else None
        else:
            return None
        if base is None:
            return None
        return base + timedelta(days=spec.offset_days, hours=spec.offset_hours)

    return None


_COMPILE_SYSTEM = """You convert natural-language resolution_date_rule strings into JSON objects
for a fixed schema used by a question generator.

Output JSON only, matching this shape:
{"items":[{"template_id":"<id>","spec":{...}}, ...]}

Each spec object must have:
- kind: one of offset_from_anchor | calendar_in_year | metadata_date | window_end | none

For kind offset_from_anchor:
- anchor: for question_family "content": release_date | question_start | question_expiration | metadata_field
- anchor: for question_family "event" or "entity_stat": event_datetime | question_start | question_expiration | metadata_field
- metadata_key: required when anchor is metadata_field (snake_case field name on the entity/event)
- offset_days: integer (default 0)
- offset_hours: integer (default 0)

For kind calendar_in_year:
- calendar_month: 1-12, calendar_day: 1-31
- year_policy: release_year | release_year_plus_1 | event_year | event_year_plus_1 | static_context_year
  (use event_year / event_year_plus_1 for sports events; release_* for entertainment content)

For kind metadata_date:
- metadata_key: field containing an ISO or calendar date

For kind window_end:
- anchor as above, end_offset_days: integer (resolution at anchor date + this many days)

For kind none:
- use when the rule explicitly says there is no automated resolution date (rare).

Map informal phrases carefully:
- For question_family "content", when the rule says **start_date**, **start date**,
  **question start**, or when the resolution should be measured from when the
  question **opens** (trading window), use anchor **question_start**. In this
  product, per-entity content rows set question_start to a fixed offset before
  release_date (see generator ``_content_dates``); do NOT map "start_date" to
  release_date unless the rule explicitly refers to theatrical/opening/**release**
  date or premiere.
- For sports, kickoff / first pitch / scheduled game time = **event_datetime**.

Rules:
"""


def compile_resolution_rules_batch_openai(
    entries: List[Tuple[str, str, str]],
    settings: dict[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> Dict[str, ResolutionDateSpec]:
    """Compile (template_id, question_family, rule_text) rows via OpenAI.

    Returns mapping template_id -> spec. Raises on failure.
    """

    if not entries:
        return {}
    api_key = str(settings.get("openai_api_key") or "").strip()
    if not api_key:
        raise ValueError(
            "openai_api_key is required in settings to compile resolution_date_rule text at upload."
        )
    model = str(settings.get("model") or "gpt-4.1")
    openai_client = client or OpenAI(api_key=api_key)
    user_payload = [
        {"template_id": tid, "question_family": family, "resolution_date_rule": text}
        for tid, family, text in entries
    ]
    user_text = json.dumps({"templates": user_payload}, indent=2)
    schema = _CompiledResolutionBatch.model_json_schema()
    response_format: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "CompiledResolutionBatch",
            "schema": schema,
            "strict": False,
        },
    }
    messages = [
        {"role": "system", "content": _COMPILE_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=response_format,  # type: ignore[arg-type]
        )
    except BadRequestError as exc:
        err = str(exc).lower()
        if "response_format" not in err and "json_schema" not in err and "schema" not in err:
            raise
        response = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
    msg = response.choices[0].message
    refusal = getattr(msg, "refusal", None)
    if refusal:
        raise RuntimeError(f"Model refused resolution compile: {refusal}")
    content = msg.content
    if not content:
        raise RuntimeError("Model returned empty content for resolution compile")
    batch = _CompiledResolutionBatch.model_validate_json(content)
    out: dict[str, ResolutionDateSpec] = {}
    expected_ids = {e[0] for e in entries}
    for item in batch.items:
        if item.template_id not in expected_ids:
            raise ValueError(f"Unexpected template_id in compile result: {item.template_id!r}")
        out[item.template_id] = item.spec
    missing = expected_ids - set(out)
    if missing:
        raise ValueError(f"Resolution compile missing template ids: {sorted(missing)}")
    return out


def maybe_compile_resolution_for_template_data(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> dict[str, Any]:
    """If data has a non-empty resolution_date_rule and is not stock, set resolution_date_spec.

    Common phrases like "start_date + N days" are inferred deterministically first
    (no API). Otherwise existing ``resolution_date_spec`` is kept when present;
    if absent, OpenAI compiles the rule text.

    Returns a new dict (mutates copy only). Raises ValueError/RuntimeError on failure.
    """

    out = dict(data)
    family = str(out.get("question_family") or "").strip()
    if family == "stock":
        out.pop("resolution_date_spec", None)
        out.pop("resolution_date_rule", None)
        return out
    rule = str(out.get("resolution_date_rule") or "").strip()
    if not rule:
        return out

    inferred = _try_infer_resolution_spec_from_rule(rule, family)
    if inferred is not None:
        out["resolution_date_spec"] = inferred.model_dump(mode="json")
        return out

    existing = out.get("resolution_date_spec")
    if existing is not None:
        if not isinstance(existing, dict):
            raise ValueError("resolution_date_spec must be an object")
        parse_resolution_date_spec_dict(existing)
        return out
    compiled = compile_resolution_rules_batch_openai(
        [(str(out["id"]), family, rule)],
        settings,
        client=client,
    )
    tid = str(out["id"])
    spec = compiled.get(tid)
    if spec is None:
        raise ValueError(f"Resolution compile produced no spec for {tid!r}")
    out["resolution_date_spec"] = spec.model_dump(mode="json")
    return out
