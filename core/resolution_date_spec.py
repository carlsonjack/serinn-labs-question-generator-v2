"""Compile and evaluate per-template date rules for start, expiration, and resolution (non-stock).

Natural-language ``*_date_rule`` strings are converted to structured
``ResolutionDateSpec`` at template upload: common phrases are inferred locally,
then OpenAI fills in the rest. Generation evaluates the spec deterministically
without calling the API.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from openai import BadRequestError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.date_coercion import parse_entity_calendar_date
from core.date_rules import parse_event_datetime

logger = logging.getLogger(__name__)

DateRuleField = Literal["start", "expiration", "resolution"]

ResolutionKind = Literal[
    "offset_from_anchor",
    "calendar_in_year",
    "metadata_date",
    "window_end",
    "none",
    "absolute_calendar_date",
    "local_time_on_anchor_date",
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
    """Structured date rule (start, expiration, or resolution) from upload-time compile."""

    model_config = ConfigDict(extra="forbid")

    kind: ResolutionKind
    anchor: Optional[str] = None
    metadata_key: Optional[str] = None
    offset_days: int = 0
    offset_hours: int = 0
    calendar_month: Optional[int] = Field(default=None, ge=1, le=12)
    calendar_day: Optional[int] = Field(default=None, ge=1, le=31)
    calendar_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    year_policy: Optional[YearPolicy] = None
    end_offset_days: Optional[int] = None
    local_hour: Optional[int] = Field(default=None, ge=0, le=23)
    local_minute: Optional[int] = Field(default=None, ge=0, le=59)
    iana_timezone: Optional[str] = None

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
        elif self.kind == "absolute_calendar_date":
            if self.calendar_year is None or self.calendar_month is None or self.calendar_day is None:
                raise ValueError("absolute_calendar_date requires calendar_year, calendar_month, calendar_day")
        elif self.kind == "local_time_on_anchor_date":
            if not self.anchor:
                raise ValueError("local_time_on_anchor_date requires anchor")
            if self.local_hour is None or self.local_minute is None:
                raise ValueError("local_time_on_anchor_date requires local_hour and local_minute")
            tz = (self.iana_timezone or "").strip()
            if not tz:
                raise ValueError("local_time_on_anchor_date requires iana_timezone")
            try:
                ZoneInfo(tz)
            except Exception as exc:
                raise ValueError(f"invalid iana_timezone: {tz!r}") from exc
            if self.anchor == "metadata_field" and not (self.metadata_key or "").strip():
                raise ValueError("metadata_field anchor requires metadata_key")
        return self


class _CompiledTemplateDateRuleItem(BaseModel):
    template_id: str
    field: DateRuleField
    spec: ResolutionDateSpec


class _CompiledTemplateDateRulesBatch(BaseModel):
    items: List[_CompiledTemplateDateRuleItem]


@dataclass(frozen=True)
class ContentResolutionContext:
    release_date: date
    question_start: datetime
    question_expiration: datetime
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
        raise ValueError("date rule spec must be an object")
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
_EVENT_MINUS_HOURS = re.compile(
    r"(?i)(?:event|game|kickoff)[_\s-]*(?:date|datetime)?[_\s-]*(?:minus|[-–])[_\s]*(\d+)[_\s-]*(?:h|hr|hrs|hours?)\b",
)
_EVENT_SNAKE_MINUS_HOURS = re.compile(
    r"(?i)event[_\s-]*date[_\s-]*minus[_\s-]*(\d+)[_\s-]*hours?",
)
_SLASH_MDY = re.compile(r"\b(1[0-2]|0?[1-9])/(3[01]|[12][0-9]|0?[1-9])/(20[2-9]\d)\b")
_ISO_YMD = re.compile(r"\b(20[2-9]\d)-(1[0-2]|0[1-9])-(3[01]|[12][0-9]|0[1-9])\b")


def _try_infer_spec_from_rule(
    rule: str,
    question_family: str,
    rule_field: DateRuleField,
) -> Optional[ResolutionDateSpec]:
    """Map common phrasing to a spec without OpenAI (upload path)."""

    fam = (question_family or "").strip().lower()
    if fam == "stock":
        return None
    if not (rule or "").strip():
        return None
    text = rule.strip()

    m = _ISO_YMD.fullmatch(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return ResolutionDateSpec(
            kind="absolute_calendar_date",
            calendar_year=y,
            calendar_month=mo,
            calendar_day=d,
        )
    m = _SLASH_MDY.fullmatch(text)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return ResolutionDateSpec(
            kind="absolute_calendar_date",
            calendar_year=y,
            calendar_month=mo,
            calendar_day=d,
        )

    if fam in ("event", "entity_stat"):
        m = _EVENT_SNAKE_MINUS_HOURS.search(text) or _EVENT_MINUS_HOURS.search(text)
        if m:
            n = int(m.group(1))
            return ResolutionDateSpec(
                kind="offset_from_anchor",
                anchor="event_datetime",
                offset_days=0,
                offset_hours=-n,
            )

    m = _START_DATE_PLUS_DAYS.search(text)
    if m:
        n = int(m.group(2))
        return ResolutionDateSpec(kind="offset_from_anchor", anchor="question_start", offset_days=n)
    m = _EXPIRATION_DATE_PLUS_DAYS.search(text)
    if m:
        n = int(m.group(2))
        return ResolutionDateSpec(
            kind="offset_from_anchor", anchor="question_expiration", offset_days=n
        )
    m = _RELEASE_DATE_PLUS_DAYS.search(text)
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


def _event_anchor_datetime(ctx: EventResolutionContext, spec: ResolutionDateSpec) -> Optional[datetime]:
    anchor = (spec.anchor or "").strip()
    if anchor == "event_datetime":
        return ctx.event_datetime
    if anchor == "question_start":
        return ctx.question_start
    if anchor == "question_expiration":
        return ctx.question_expiration
    if anchor == "metadata_field":
        d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        return datetime.combine(d, time.min) if d else None
    return None


def _local_wall_time_to_naive_utc(
    anchor_instant_naive_utc: datetime,
    *,
    local_hour: int,
    local_minute: int,
    iana_timezone: str,
) -> datetime:
    """Anchor instant is naive UTC; interpret its calendar moment in ``iana_timezone``, set wall clock, return naive UTC."""

    zi = ZoneInfo(iana_timezone.strip())
    aware = anchor_instant_naive_utc.replace(tzinfo=timezone.utc)
    local = aware.astimezone(zi)
    shifted = local.replace(hour=local_hour, minute=local_minute, second=0, microsecond=0)
    return shifted.astimezone(timezone.utc).replace(tzinfo=None)


def _local_wall_time_on_calendar_date_to_naive_utc(
    anchor_date: date,
    *,
    local_hour: int,
    local_minute: int,
    iana_timezone: str,
) -> datetime:
    zi = ZoneInfo(iana_timezone.strip())
    local = datetime.combine(anchor_date, time(local_hour, local_minute), tzinfo=zi)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def evaluate_template_datetime_for_event(
    spec: Optional[ResolutionDateSpec],
    ctx: EventResolutionContext,
) -> Optional[datetime]:
    """Return naive UTC datetime for this spec, or None to keep caller baseline."""

    if spec is None or spec.kind == "none":
        return None

    if spec.kind == "metadata_date":
        d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        if d is None:
            return None
        return datetime.combine(d, time.min)

    if spec.kind == "absolute_calendar_date":
        assert spec.calendar_year is not None and spec.calendar_month is not None and spec.calendar_day is not None
        d = date(spec.calendar_year, spec.calendar_month, spec.calendar_day)
        return datetime.combine(d, time.min)

    if spec.kind == "calendar_in_year" and spec.year_policy and spec.calendar_month and spec.calendar_day:
        year = _resolve_year_for_calendar_event(spec.year_policy, ctx)
        d = date(year, spec.calendar_month, spec.calendar_day)
        return datetime.combine(d, time.min)

    if spec.kind == "local_time_on_anchor_date":
        assert spec.local_hour is not None and spec.local_minute is not None and spec.iana_timezone
        base = _event_anchor_datetime(ctx, spec)
        if base is None:
            return None
        return _local_wall_time_to_naive_utc(
            base,
            local_hour=spec.local_hour,
            local_minute=spec.local_minute,
            iana_timezone=spec.iana_timezone,
        )

    if spec.kind == "window_end":
        eff = spec if spec.anchor else spec.model_copy(update={"anchor": "event_datetime"})
        base = _event_anchor_datetime(ctx, eff)
        if base is None:
            return None
        return base + timedelta(days=int(spec.end_offset_days or 0))

    if spec.kind == "offset_from_anchor":
        eff = spec if spec.anchor else spec.model_copy(update={"anchor": "event_datetime"})
        base = _event_anchor_datetime(ctx, eff)
        if base is None:
            return None
        return base + timedelta(days=spec.offset_days, hours=spec.offset_hours)

    return None


def compute_resolution_datetime_for_event(
    spec: Optional[ResolutionDateSpec],
    ctx: EventResolutionContext,
) -> Optional[datetime]:
    """Return naive resolution datetime, or None to keep YAML-derived resolution."""

    return evaluate_template_datetime_for_event(spec, ctx)


def evaluate_template_datetime_for_content(
    spec: Optional[ResolutionDateSpec],
    ctx: ContentResolutionContext,
) -> Optional[datetime]:
    """Return naive UTC datetime for a content template date rule."""

    if spec is None or spec.kind == "none":
        return None

    if spec.kind == "metadata_date":
        d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        if d is None:
            return None
        return datetime.combine(d, time.min)

    if spec.kind == "absolute_calendar_date":
        assert spec.calendar_year is not None and spec.calendar_month is not None and spec.calendar_day is not None
        d = date(spec.calendar_year, spec.calendar_month, spec.calendar_day)
        return datetime.combine(d, time.min)

    if spec.kind == "calendar_in_year" and spec.year_policy and spec.calendar_month and spec.calendar_day:
        year = _resolve_year_for_calendar(spec.year_policy, ctx)
        d = date(year, spec.calendar_month, spec.calendar_day)
        return datetime.combine(d, time.min)

    if spec.kind == "local_time_on_anchor_date":
        assert spec.local_hour is not None and spec.local_minute is not None and spec.iana_timezone
        anchor = spec.anchor or "release_date"
        base_d: date | None
        if anchor == "release_date":
            base_d = ctx.release_date
        elif anchor == "question_start":
            base_d = ctx.question_start.date()
        elif anchor == "question_expiration":
            base_d = ctx.question_expiration.date()
        elif anchor == "metadata_field":
            base_d = _metadata_date(ctx.metadata, spec.metadata_key or "")
        else:
            return None
        if base_d is None:
            return None
        return _local_wall_time_on_calendar_date_to_naive_utc(
            base_d,
            local_hour=spec.local_hour,
            local_minute=spec.local_minute,
            iana_timezone=spec.iana_timezone,
        )

    if spec.kind == "window_end":
        anchor = spec.anchor or "release_date"
        base: date | None
        if anchor == "release_date":
            base = ctx.release_date
        elif anchor == "question_start":
            base = ctx.question_start.date()
        elif anchor == "question_expiration":
            base = ctx.question_expiration.date()
        elif anchor == "metadata_field":
            base = _metadata_date(ctx.metadata, spec.metadata_key or "")
        else:
            return None
        if base is None:
            return None
        end_d = base + timedelta(days=int(spec.end_offset_days or 0))
        return datetime.combine(end_d, time.min)

    if spec.kind == "offset_from_anchor":
        anchor = spec.anchor or ""
        base_dt: datetime | None = None
        if anchor == "release_date":
            base_dt = datetime.combine(ctx.release_date, time.min)
        elif anchor == "question_start":
            base_dt = ctx.question_start
        elif anchor == "question_expiration":
            base_dt = ctx.question_expiration
        elif anchor == "metadata_field":
            md = _metadata_date(ctx.metadata, spec.metadata_key or "")
            base_dt = datetime.combine(md, time.min) if md else None
        else:
            return None
        if base_dt is None:
            return None
        return base_dt + timedelta(
            days=spec.offset_days,
            hours=spec.offset_hours,
        )

    return None


def content_spec_emits_non_midnight(spec: Optional[ResolutionDateSpec]) -> bool:
    """True when ISO output for content should include a non-midnight clock (per product rules)."""

    if spec is None or spec.kind == "none":
        return False
    if spec.kind == "local_time_on_anchor_date":
        return True
    if spec.kind == "offset_from_anchor" and spec.offset_hours != 0:
        return True
    return False


def format_content_template_datetime(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def compute_resolution_date_for_content(
    spec: Optional[ResolutionDateSpec],
    ctx: ContentResolutionContext,
) -> Optional[date]:
    """Return calendar resolution date, or None to fall back to legacy heuristics."""

    dt = evaluate_template_datetime_for_content(spec, ctx)
    if dt is None:
        return None
    return dt.date()


_COMPILE_SYSTEM = """You convert natural-language template date rule strings into JSON objects
for a fixed schema used by a question generator.

Output JSON only, matching this shape:
{"items":[{"template_id":"<id>","field":"start|expiration|resolution","spec":{...}}, ...]}

Each spec object must have:
- kind: one of offset_from_anchor | calendar_in_year | metadata_date | window_end | none
  | absolute_calendar_date | local_time_on_anchor_date

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

For kind absolute_calendar_date:
- calendar_year, calendar_month, calendar_day: fixed calendar date (no year_policy)

For kind local_time_on_anchor_date:
- anchor as for offset_from_anchor (same question_family rules)
- local_hour: 0-23, local_minute: 0-59
- iana_timezone: IANA name e.g. America/New_York
- For event/sports: wall time on the anchor instant's calendar date in that zone, stored as naive UTC.

For kind metadata_date:
- metadata_key: field containing an ISO or calendar date

For kind window_end:
- anchor as above, end_offset_days: integer (date at anchor date + this many days, midnight UTC)

For kind none:
- use when the rule explicitly says there is no automated date for this field (rare).

Field-specific guidance:
- field "start": prefer anchors event_datetime (sports) or release_date / question_start (content). Avoid anchor question_start when it would mean "start relative to itself" unless the rule text clearly references opening relative to another anchor.
- field "expiration": same anchor vocabulary; avoid circular self-reference.
- field "resolution": same as historical resolution_date_rule behavior.

Map informal phrases:
- For question_family "content", **start_date** / question start / when the question **opens** → anchor **question_start** (not release_date unless text says release/premiere).
- Sports kickoff / first pitch / game time = **event_datetime**.
- Phrases like "11am Eastern on event day" → local_time_on_anchor_date with iana_timezone America/New_York.

Rules:
"""


def compile_template_date_rules_batch_openai(
    entries: List[Tuple[str, str, DateRuleField, str]],
    settings: dict[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> Dict[Tuple[str, DateRuleField], ResolutionDateSpec]:
    """Compile (template_id, question_family, field, rule_text) via OpenAI.

    Returns mapping (template_id, field) -> spec. Raises on failure.
    """

    if not entries:
        return {}
    api_key = str(settings.get("openai_api_key") or "").strip()
    if not api_key:
        raise ValueError(
            "openai_api_key is required in settings to compile template date rule text at upload."
        )
    model = str(settings.get("model") or "gpt-4.1")
    openai_client = client or OpenAI(api_key=api_key)
    user_payload = [
        {"template_id": tid, "question_family": family, "field": field, "rule": text}
        for tid, family, field, text in entries
    ]
    user_text = json.dumps({"templates": user_payload}, indent=2)
    schema = _CompiledTemplateDateRulesBatch.model_json_schema()
    response_format: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "CompiledTemplateDateRulesBatch",
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
        raise RuntimeError(f"Model refused template date rule compile: {refusal}")
    content = msg.content
    if not content:
        raise RuntimeError("Model returned empty content for template date rule compile")
    raw_payload = json.loads(content)
    if isinstance(raw_payload, dict):
        items = raw_payload.get("items")
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and "field" not in it:
                    it["field"] = "resolution"
    batch = _CompiledTemplateDateRulesBatch.model_validate(raw_payload)
    out: dict[tuple[str, DateRuleField], ResolutionDateSpec] = {}
    expected = {(e[0], e[2]) for e in entries}
    for item in batch.items:
        key = (item.template_id, item.field)
        if key not in expected:
            raise ValueError(f"Unexpected compile result key: {key!r}")
        out[key] = item.spec
    missing = expected - set(out)
    if missing:
        raise ValueError(f"Template date compile missing keys: {sorted(missing)}")
    return out


def compile_resolution_rules_batch_openai(
    entries: List[Tuple[str, str, str]],
    settings: dict[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> Dict[str, ResolutionDateSpec]:
    """Compile legacy (template_id, question_family, rule_text) rows — resolution field only."""

    if not entries:
        return {}
    extended: List[Tuple[str, str, DateRuleField, str]] = [
        (tid, fam, "resolution", text) for tid, fam, text in entries
    ]
    combined = compile_template_date_rules_batch_openai(extended, settings, client=client)
    return {tid: combined[(tid, "resolution")] for tid, _, _ in entries}


def _process_rule_field(
    out: dict[str, Any],
    family: str,
    field: DateRuleField,
    rule_key: str,
    spec_key: str,
    batch_entries: List[Tuple[str, str, DateRuleField, str]],
) -> None:
    rule = str(out.get(rule_key) or "").strip()
    if not rule:
        return
    inferred = _try_infer_spec_from_rule(rule, family, field)
    if inferred is not None:
        out[spec_key] = inferred.model_dump(mode="json")
        return
    existing = out.get(spec_key)
    if existing is not None:
        if not isinstance(existing, dict):
            raise ValueError(f"{spec_key} must be an object")
        parse_resolution_date_spec_dict(existing)
        return
    batch_entries.append((str(out["id"]), family, field, rule))


def maybe_compile_resolution_for_template_data(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> dict[str, Any]:
    """Compile resolution / start / expiration date rules at upload (non-stock).

    Common phrases are inferred deterministically first. Existing ``*_spec`` objects
    are kept when present and valid. Otherwise OpenAI compiles remaining rule text
    in a single batch per template.

    Returns a new dict. Raises ValueError/RuntimeError on failure.
    """

    out = dict(data)
    family = str(out.get("question_family") or "").strip()
    if family == "stock":
        for key in (
            "resolution_date_spec",
            "resolution_date_rule",
            "start_date_spec",
            "start_date_rule",
            "expiration_date_spec",
            "expiration_date_rule",
        ):
            out.pop(key, None)
        return out

    batch: List[Tuple[str, str, DateRuleField, str]] = []
    _process_rule_field(out, family, "resolution", "resolution_date_rule", "resolution_date_spec", batch)
    _process_rule_field(out, family, "start", "start_date_rule", "start_date_spec", batch)
    _process_rule_field(out, family, "expiration", "expiration_date_rule", "expiration_date_spec", batch)

    if batch:
        try:
            compiled = compile_template_date_rules_batch_openai(batch, settings, client=client)
        except (ValueError, RuntimeError) as exc:
            raise RuntimeError(f"OpenAI template date compile failed ({batch!r}): {exc}") from exc
        for tid, fam, field, _rule in batch:
            spec = compiled.get((tid, field))
            if spec is None:
                raise ValueError(f"Compile produced no spec for template_id={tid!r} field={field!r}")
            if field == "resolution":
                out["resolution_date_spec"] = spec.model_dump(mode="json")
            elif field == "start":
                out["start_date_spec"] = spec.model_dump(mode="json")
            else:
                out["expiration_date_spec"] = spec.model_dump(mode="json")
    return out
