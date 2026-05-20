"""Deterministic content-list question generation."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from itertools import combinations
from typing import Any

from core.date_coercion import parse_entity_calendar_date
from core.parsers.contracts import ContentEntity
from core.resolution_date_spec import (
    ContentResolutionContext,
    ResolutionDateSpec,
    content_spec_emits_non_midnight,
    evaluate_template_datetime_for_content,
    format_content_template_datetime,
)
from core.template_config.schema import QuestionTemplate

IMPORT_OUTPUT_COLUMNS: list[str] = [
    "Topic Import ID",
    "Question",
    "Answer Type",
    "Answer Options",
    "Start Date",
    "Expiration Date",
    "Resolution Date",
    "Priority",
]
CONTENT_OUTPUT_COLUMNS = IMPORT_OUTPUT_COLUMNS


@dataclass(frozen=True)
class ImportQuestionRow:
    topic_import_id: str
    question: str
    answer_type: str
    answer_options: str
    start_date: str
    expiration_date: str
    resolution_date: str
    priority: int | str

    def to_import_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {
            "Topic Import ID": data["topic_import_id"],
            "Question": data["question"],
            "Answer Type": data["answer_type"],
            "Answer Options": data["answer_options"],
            "Start Date": data["start_date"],
            "Expiration Date": data["expiration_date"],
            "Resolution Date": data["resolution_date"],
            "Priority": data["priority"],
        }


@dataclass(frozen=True)
class ContentQuestionDates:
    start_date: str
    expiration_date: str
    resolution_date: str


def _calendar_date_to_iso_midnight(d: date) -> str:
    return datetime.combine(d, time.min).isoformat(timespec="seconds")


class ContentPlanner:
    """Build import rows from normalized content entities and content templates."""

    def __init__(
        self,
        entities: Sequence[ContentEntity],
        templates: Sequence[QuestionTemplate],
        settings: Mapping[str, Any],
        *,
        topic_import_id: str,
    ) -> None:
        self.entities = sorted(
            [
                entity
                for entity in entities
                if _entity_release_date(entity) is not None
                and _within_date_filter(_entity_release_date(entity), settings)
            ],
            key=_entity_sort_key,
        )
        self.templates = sorted(templates, key=_template_sort_key)
        self.settings = settings
        self.topic_import_id = topic_import_id
        if not self.entities:
            raise ValueError("Content generation requires at least one dated content entity.")
        if not self.templates:
            raise ValueError("Content generation requires at least one content template.")

    def generate(self) -> list[ImportQuestionRow]:
        rows: list[ImportQuestionRow] = []
        for template in self.templates:
            rows.extend(self._generate_for_template(template))

        max_total = _effective_max_generated_questions(self.settings)
        if max_total is not None:
            rows = rows[:max_total]
        if not rows:
            raise ValueError("No content rows were generated from the selected inputs/templates.")
        return rows

    def _generate_for_template(self, template: QuestionTemplate) -> list[ImportQuestionRow]:
        if _is_multi_entity_choice_template(template):
            return self._generate_multi_entity_choice(template)
        if _is_pairwise_template(template):
            return self._generate_pairwise(template)
        if _is_static_template(template):
            row = self._build_static_row(template)
            return [row] if row is not None else []
        return [self._build_entity_row(template, entity) for entity in self.entities]

    def _generate_multi_entity_choice(self, template: QuestionTemplate) -> list[ImportQuestionRow]:
        count = _multi_entity_count(template)
        if count < 2:
            raise ValueError(f"Template {template.id!r} requires entity_count >= 2.")

        rows: list[ImportQuestionRow] = []
        by_date: dict[date, list[ContentEntity]] = defaultdict(list)
        for entity in self.entities:
            release_date = _entity_release_date(entity)
            if release_date is not None:
                by_date[release_date].append(entity)

        for release_date in sorted(by_date):
            entities = sorted(by_date[release_date], key=_entity_sort_key)
            if len(entities) < count:
                continue
            meta = _merged_entity_metadata(entities[:count])
            rows.append(
                self._build_multi_entity_row(template, entities[:count], release_date, meta)
            )

        if not rows and len(self.entities) >= count:
            selected = self.entities[:count]
            release_date = _entity_release_date(selected[0])
            if release_date is not None:
                meta = _merged_entity_metadata(selected)
                rows.append(self._build_multi_entity_row(template, selected, release_date, meta))
        return rows

    def _build_multi_entity_row(
        self,
        template: QuestionTemplate,
        entities: Sequence[ContentEntity],
        release_date: date,
        metadata: Mapping[str, Any] | None = None,
    ) -> ImportQuestionRow:
        context = _multi_entity_context(entities)
        context.update(_default_context(self.settings, release_date))
        dates = _content_dates(template, release_date, self.settings, metadata=metadata)
        return ImportQuestionRow(
            topic_import_id=self.topic_import_id,
            question=_fill_placeholders(template.question, context),
            answer_type=template.answer_type,
            answer_options=_answer_options(template, context),
            start_date=dates.start_date,
            expiration_date=dates.expiration_date,
            resolution_date=dates.resolution_date,
            priority=template.priority,
        )

    def _generate_pairwise(self, template: QuestionTemplate) -> list[ImportQuestionRow]:
        rows: list[ImportQuestionRow] = []
        by_date: dict[date, list[ContentEntity]] = defaultdict(list)
        for entity in self.entities:
            release_date = _entity_release_date(entity)
            if release_date is not None:
                by_date[release_date].append(entity)

        for release_date in sorted(by_date):
            entities = sorted(by_date[release_date], key=_entity_sort_key)
            for release_a, release_b in combinations(entities, 2):
                context = _entity_context(release_a, prefix="RELEASE_A")
                context.update(_entity_context(release_b, prefix="RELEASE_B"))
                context.update(_default_context(self.settings, release_date))
                meta = _merged_entity_metadata([release_a, release_b])
                dates = _content_dates(template, release_date, self.settings, metadata=meta)
                rows.append(
                    ImportQuestionRow(
                        topic_import_id=self.topic_import_id,
                        question=_fill_placeholders(template.question, context),
                        answer_type=template.answer_type,
                        answer_options=_answer_options(template, context),
                        start_date=dates.start_date,
                        expiration_date=dates.expiration_date,
                        resolution_date=dates.resolution_date,
                        priority=template.priority,
                    )
                )
        return rows

    def _build_entity_row(
        self,
        template: QuestionTemplate,
        entity: ContentEntity,
    ) -> ImportQuestionRow:
        release_date = _entity_release_date(entity)
        if release_date is None:
            raise ValueError(f"Content entity {entity.entity_id!r} is missing release_date.")
        context = _entity_context(entity)
        context.update(_default_context(self.settings, release_date))
        dates = _content_dates(template, release_date, self.settings, metadata=entity.metadata)
        return ImportQuestionRow(
            topic_import_id=self.topic_import_id,
            question=_fill_placeholders(template.question, context),
            answer_type=template.answer_type,
            answer_options=_answer_options(template, context),
            start_date=dates.start_date,
            expiration_date=dates.expiration_date,
            resolution_date=dates.resolution_date,
            priority=template.priority,
        )

    def _build_static_row(self, template: QuestionTemplate) -> ImportQuestionRow | None:
        year = _static_year(self.settings)
        context = _default_context(self.settings, date(year, 1, 1))
        dates = _static_row_dates(template, self.settings, year)
        return ImportQuestionRow(
            topic_import_id=self.topic_import_id,
            question=_fill_placeholders(template.question, context),
            answer_type=template.answer_type,
            answer_options=_answer_options(template, context),
            start_date=dates.start_date,
            expiration_date=dates.expiration_date,
            resolution_date=dates.resolution_date,
            priority=template.priority,
        )


def _template_sort_key(template: QuestionTemplate) -> tuple[int, int, str]:
    static_weight = 1 if _is_static_template(template) else 0
    return (static_weight, _optional_positive_int(template.priority) or 999, template.id)


def _is_pairwise_template(template: QuestionTemplate) -> bool:
    text = f"{template.question} {template.answer_options}".upper()
    return "RELEASE_A" in text and "RELEASE_B" in text


def _is_multi_entity_choice_template(template: QuestionTemplate) -> bool:
    if template.generation_strategy == "multi_entity_choice":
        return True
    text = f"{template.question} {template.answer_options}".upper()
    return bool(re.search(r"\[(?:ENTITY|MOVIE|TITLE)_[A-Z]\]", text))


def _multi_entity_count(template: QuestionTemplate) -> int:
    if template.entity_count:
        return template.entity_count
    text = f"{template.question} {template.answer_options}".upper()
    letters = [
        match.group(1)
        for match in re.finditer(r"\[(?:ENTITY|MOVIE|TITLE)_([A-Z])\]", text)
    ]
    if not letters:
        return 0
    return max(ord(letter) - ord("A") + 1 for letter in letters)


def _is_static_template(template: QuestionTemplate) -> bool:
    text = f"{template.question} {template.answer_options}".upper()
    static_markers = {"ARTIST_A", "ARTIST_B", "TOUR_CHART_SOURCE", "YEAR"}
    entity_markers = {"ALBUM_OR_RELEASE", "ALBUM_OR_ARTIST", "RELEASE_A", "TITLE", "MOVIE_A", "ENTITY_A"}
    return any(marker in text for marker in static_markers) and not any(
        marker in text for marker in entity_markers
    )


def _entity_sort_key(entity: ContentEntity) -> tuple[date, str, str]:
    return (
        _entity_release_date(entity) or date.max,
        entity.display_name.lower(),
        entity.entity_id,
    )


def _entity_release_date(entity: ContentEntity) -> date | None:
    for key in ("release_date", "premiere_date", "air_date", "date"):
        raw = entity.metadata.get(key)
        if raw not in (None, ""):
            return _parse_date(raw)
    return None


def _within_date_filter(value: date | None, settings: Mapping[str, Any]) -> bool:
    if value is None:
        return False
    date_filter = settings.get("date_filter")
    if not isinstance(date_filter, Mapping):
        return True
    start = date_filter.get("start")
    end = date_filter.get("end")
    if start and value < _parse_date(start):
        return False
    if end and value > _parse_date(end):
        return False
    return True


def _parse_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return parse_entity_calendar_date(raw)


def _entity_context(entity: ContentEntity, prefix: str | None = None) -> dict[str, str]:
    title = str(entity.metadata.get("title") or entity.display_name).strip()
    artist = str(entity.metadata.get("artist") or "").strip()
    display = f"{title} by {artist}" if artist and title and " by " not in title else entity.display_name
    release_date = _entity_release_date(entity)
    values = {
        "ENTITY": entity.display_name,
        "TITLE": title,
        "ALBUM_OR_RELEASE": display,
        "ALBUM_OR_ARTIST": display,
        "RELEASE": display,
        "ARTIST": artist,
        "MOVIE": display,
        "MOVIE_TITLE": title,
        "RELEASE_DATE": release_date.isoformat() if release_date else "",
    }
    for key, value in entity.metadata.items():
        if value not in (None, ""):
            values.setdefault(_metadata_placeholder_key(key), str(value))
    if prefix:
        return {
            prefix: display,
            f"{prefix}_TITLE": title,
            f"{prefix}_ARTIST": artist,
            f"{prefix}_RELEASE_DATE": release_date.isoformat() if release_date else "",
        }
    return values


def _multi_entity_context(entities: Sequence[ContentEntity]) -> dict[str, str]:
    context: dict[str, str] = {}
    for index, entity in enumerate(entities):
        letter = chr(ord("A") + index)
        entity_context = _entity_context(entity)
        display = entity_context.get("ENTITY", entity.display_name)
        title = entity_context.get("TITLE", display)
        release_date = entity_context.get("RELEASE_DATE", "")
        context[f"ENTITY_{letter}"] = display
        context[f"MOVIE_{letter}"] = display
        context[f"TITLE_{letter}"] = title
        context[f"MOVIE_{letter}_TITLE"] = title
        context[f"RELEASE_DATE_{letter}"] = release_date
    return context


def _metadata_placeholder_key(key: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")


def _default_context(settings: Mapping[str, Any], base_date: date) -> dict[str, str]:
    cfg = _content_config(settings)
    static = cfg.get("static_values")
    values: dict[str, str] = {
        "CHART_NAME": "Billboard 200",
        "TOUR_CHART_SOURCE": "Pollstar",
        "YEAR": str(base_date.year),
        "ARTIST_A": "Taylor Swift",
        "ARTIST_B": "Bad Bunny",
        "ARTIST_C": "Beyonce",
        "ARTIST_D": "Coldplay",
    }
    if isinstance(static, Mapping):
        values.update({str(k).upper(): str(v) for k, v in static.items() if v is not None})
    return values


def _answer_options(template: QuestionTemplate, context: Mapping[str, str]) -> str:
    if template.answer_type == "yes_no":
        return ""
    return _fill_placeholders(template.answer_options, context)


_BRACKET_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")
_BRACE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _fill_placeholders(text: str, context: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).upper()
        return str(context.get(key, match.group(0)))

    out = _BRACKET_PLACEHOLDER_RE.sub(repl, text)
    return _BRACE_PLACEHOLDER_RE.sub(repl, out)


def _merged_entity_metadata(entities: Sequence[ContentEntity]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for ent in entities:
        merged.update(ent.metadata or {})
    return merged


def _format_content_field_iso(spec: ResolutionDateSpec | None, dt: datetime) -> str:
    if spec is not None and content_spec_emits_non_midnight(spec):
        return format_content_template_datetime(dt)
    if dt.time() != time.min:
        return format_content_template_datetime(dt)
    return _calendar_date_to_iso_midnight(dt.date())


def _optional_template_date_spec(template: QuestionTemplate, attr: str) -> ResolutionDateSpec | None:
    raw = getattr(template, attr, None)
    if not raw:
        return None
    return ResolutionDateSpec.model_validate(raw)


def _template_resolution_spec(template: QuestionTemplate) -> ResolutionDateSpec | None:
    return _optional_template_date_spec(template, "resolution_date_spec")


def _content_dates(
    template: QuestionTemplate,
    release_date: date,
    settings: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ContentQuestionDates:
    start_day = release_date - timedelta(days=7)
    exp_day = release_date - timedelta(days=1)
    start_dt = datetime.combine(start_day, time.min)
    exp_dt = datetime.combine(exp_day, time.min)
    meta = dict(metadata or {})

    start_spec = _optional_template_date_spec(template, "start_date_spec")
    ctx_start = ContentResolutionContext(
        release_date=release_date,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata=meta,
        static_year=None,
    )
    if start_spec:
        o = evaluate_template_datetime_for_content(start_spec, ctx_start)
        if o is not None:
            start_dt = o

    exp_spec = _optional_template_date_spec(template, "expiration_date_spec")
    ctx_exp = ContentResolutionContext(
        release_date=release_date,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata=meta,
        static_year=None,
    )
    if exp_spec:
        o = evaluate_template_datetime_for_content(exp_spec, ctx_exp)
        if o is not None:
            exp_dt = o

    res_spec = _template_resolution_spec(template)
    ctx_res = ContentResolutionContext(
        release_date=release_date,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata=meta,
        static_year=None,
    )
    res_dt: datetime | None = None
    if res_spec:
        res_dt = evaluate_template_datetime_for_content(res_spec, ctx_res)
    if res_dt is None:
        res_dt = datetime.combine(
            _resolution_date_heuristic(template, release_date, settings),
            time.min,
        )
        res_fmt_spec: ResolutionDateSpec | None = None
    else:
        res_fmt_spec = res_spec

    return ContentQuestionDates(
        _format_content_field_iso(start_spec, start_dt),
        _format_content_field_iso(exp_spec, exp_dt),
        _format_content_field_iso(res_fmt_spec, res_dt),
    )


def _resolution_date_heuristic(
    template: QuestionTemplate,
    release_date: date,
    settings: Mapping[str, Any],
) -> date:
    cfg = _content_config(settings)
    overrides = cfg.get("resolution_dates")
    if isinstance(overrides, Mapping):
        raw = overrides.get(template.id) or overrides.get(template.template_type or "")
        if raw:
            return _parse_date(raw)

    text = " ".join(
        part.lower()
        for part in (template.id, template.template_type or "", template.question, template.notes or "")
    )
    if "grammy" in text or "award" in text or "nomination" in text:
        raw = cfg.get("award_resolution_date") or f"{release_date.year + 1}-11-01"
        return _parse_date(raw)
    if "longevity" in text or "stay on" in text:
        return release_date + timedelta(days=90)
    if "song count" in text or "first 30 days" in text or "hot 100" in text:
        return release_date + timedelta(days=31)
    if "peak" in text:
        return release_date + timedelta(days=60)
    return release_date + timedelta(days=14)


def _static_row_dates(
    template: QuestionTemplate,
    settings: Mapping[str, Any],
    year: int,
) -> ContentQuestionDates:
    cfg = _content_config(settings)
    start_spec = _optional_template_date_spec(template, "start_date_spec")
    exp_spec = _optional_template_date_spec(template, "expiration_date_spec")
    res_spec = _template_resolution_spec(template)
    if not (start_spec or exp_spec or (res_spec and res_spec.kind != "none")):
        return _static_dates(settings, year)

    start_day = _parse_date(str(cfg.get("static_start_date") or f"{year}-06-01"))
    end_day = _parse_date(str(cfg.get("static_expiration_date") or f"{year}-07-31"))
    res_day = _parse_date(str(cfg.get("static_resolution_date") or f"{year + 1}-01-10"))
    start_dt = datetime.combine(start_day, time.min)
    exp_dt = datetime.combine(end_day, time.min)
    rd = date(year, 1, 1)

    ctx0 = ContentResolutionContext(
        release_date=rd,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata={},
        static_year=year,
    )
    if start_spec:
        o = evaluate_template_datetime_for_content(start_spec, ctx0)
        if o is not None:
            start_dt = o

    ctx1 = ContentResolutionContext(
        release_date=rd,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata={},
        static_year=year,
    )
    if exp_spec:
        o = evaluate_template_datetime_for_content(exp_spec, ctx1)
        if o is not None:
            exp_dt = o

    res_dt = datetime.combine(res_day, time.min)
    ctx2 = ContentResolutionContext(
        release_date=rd,
        question_start=start_dt,
        question_expiration=exp_dt,
        metadata={},
        static_year=year,
    )
    res_fmt_spec: ResolutionDateSpec | None = None
    if res_spec and res_spec.kind != "none":
        hit = evaluate_template_datetime_for_content(res_spec, ctx2)
        if hit is not None:
            res_dt = hit
            res_fmt_spec = res_spec

    return ContentQuestionDates(
        _format_content_field_iso(start_spec, start_dt),
        _format_content_field_iso(exp_spec, exp_dt),
        _format_content_field_iso(res_fmt_spec, res_dt),
    )


def _static_dates(settings: Mapping[str, Any], year: int) -> ContentQuestionDates:
    cfg = _content_config(settings)
    return ContentQuestionDates(
        _calendar_date_to_iso_midnight(
            _parse_date(str(cfg.get("static_start_date") or f"{year}-06-01"))
        ),
        _calendar_date_to_iso_midnight(
            _parse_date(str(cfg.get("static_expiration_date") or f"{year}-07-31"))
        ),
        _calendar_date_to_iso_midnight(
            _parse_date(str(cfg.get("static_resolution_date") or f"{year + 1}-01-10"))
        ),
    )


def _static_year(settings: Mapping[str, Any]) -> int:
    cfg = _content_config(settings)
    if year := _optional_positive_int(cfg.get("year")):
        return year
    date_filter = settings.get("date_filter")
    if isinstance(date_filter, Mapping):
        for key in ("start", "end"):
            raw = date_filter.get(key)
            if raw:
                return _parse_date(raw).year
    return date.today().year


def _content_config(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = settings.get("content")
    return raw if isinstance(raw, Mapping) else {}


def _effective_max_generated_questions(settings: Mapping[str, Any]) -> int | None:
    content_cfg = _content_config(settings)
    n = _optional_positive_int(content_cfg.get("max_generated_questions"))
    if n is not None:
        return n
    raw = settings.get("max_generated_questions")
    return _optional_positive_int(raw)


def _optional_positive_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
