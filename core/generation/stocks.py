"""Deterministic stock question generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from core.market_calendar import iter_regular_trading_days, parse_date, quarter_number, stock_question_dates
from core.parsers.contracts import ContentEntity
from core.template_config.schema import QuestionTemplate

STOCK_OUTPUT_COLUMNS: list[str] = [
    "Topic Import ID",
    "Question",
    "Answer Type",
    "Answer Options",
    "Start Date",
    "Expiration Date",
    "Resolution Date",
    "Priority",
]


@dataclass(frozen=True)
class StockQuestionRow:
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


class StockPlanner:
    """Build stock rows from templates and a normalized watchlist."""

    def __init__(
        self,
        entities: Sequence[ContentEntity],
        templates: Sequence[QuestionTemplate],
        settings: Mapping[str, Any],
        *,
        topic_import_id: str,
    ) -> None:
        self.entities = list(entities)
        self.templates = sorted(templates, key=_template_sort_key)
        self.settings = settings
        self.topic_import_id = topic_import_id
        if not self.entities:
            raise ValueError("Stocks generation requires at least one stock in the watchlist.")
        if not self.templates:
            raise ValueError("Stocks generation requires at least one stock template.")

    def generate(self) -> list[StockQuestionRow]:
        date_filter = self.settings.get("date_filter") or {}
        start = str(date_filter.get("start") or "")
        end = str(date_filter.get("end") or start)
        if not start:
            raise ValueError("Stocks generation requires date_filter.start.")

        rows: list[StockQuestionRow] = []
        max_total = _effective_max_generated_questions(self.settings)
        questions_per_day = _questions_per_day(self.settings, len(self.templates))

        for question_date in iter_regular_trading_days(start, end):
            day_rows = self._generate_day(question_date, questions_per_day)
            remaining = None if max_total is None else max_total - len(rows)
            if remaining is not None:
                if remaining <= 0:
                    break
                day_rows = day_rows[:remaining]
            rows.extend(day_rows)
            if max_total is not None and len(rows) >= max_total:
                break
        rows = _filter_rows_by_min_start(rows, start)
        if not rows:
            raise ValueError(
                "No stock rows remain after applying minimum Start Date "
                f"(date_filter.start={start}). Widen the export window or expect fewer "
                "long-horizon templates."
            )
        return rows

    def _generate_day(self, question_date: date, questions_per_day: int) -> list[StockQuestionRow]:
        counts: dict[str, int] = {}
        used_mc_sets: set[tuple[str, ...]] = set()
        rows: list[StockQuestionRow] = []
        idx = 0
        attempts = 0
        max_attempts = max(questions_per_day * len(self.templates) * 3, questions_per_day)

        while len(rows) < questions_per_day and attempts < max_attempts:
            template = self.templates[idx % len(self.templates)]
            idx += 1
            attempts += 1
            row = self._build_row(template, question_date, counts, used_mc_sets)
            if row is not None:
                rows.append(row)
        return rows

    def _build_row(
        self,
        template: QuestionTemplate,
        question_date: date,
        counts: dict[str, int],
        used_mc_sets: set[tuple[str, ...]],
    ) -> StockQuestionRow | None:
        timeframe = _timeframe(template)
        dates = stock_question_dates(question_date, timeframe)
        selected: dict[str, ContentEntity] = {}

        if _needs_option_assets(template):
            assets = self._available_assets(counts, needed=4)[:4]
            if len(assets) < 4:
                return None
            option_key = tuple(sorted(asset.entity_id for asset in assets))
            if option_key in used_mc_sets:
                return None
            used_mc_sets.add(option_key)
            self._commit_assets(counts, assets)
            for pos, asset in enumerate(assets, start=1):
                selected[f"ASSET_{pos}"] = asset
            answer_options = _fill_placeholders(template.answer_options, question_date, selected)
        else:
            asset = self._choose_asset(counts)
            if asset is None:
                return None
            selected["ASSET"] = asset
            answer_options = "" if template.answer_type == "yes_no" else template.answer_options

        question = _fill_placeholders(template.question, question_date, selected)
        return StockQuestionRow(
            topic_import_id=self.topic_import_id,
            question=question,
            answer_type=template.answer_type,
            answer_options=answer_options,
            start_date=dates.start_date,
            expiration_date=dates.expiration_date,
            resolution_date=dates.resolution_date,
            priority=template.priority,
        )

    def _choose_asset(self, counts: dict[str, int]) -> ContentEntity | None:
        chosen = self._available_assets(counts, needed=1)
        if not chosen:
            return None
        asset = chosen[0]
        counts[asset.entity_id] = counts.get(asset.entity_id, 0) + 1
        return asset

    def _commit_assets(self, counts: dict[str, int], assets: Sequence[ContentEntity]) -> None:
        for asset in assets:
            counts[asset.entity_id] = counts.get(asset.entity_id, 0) + 1

    def _available_assets(self, counts: dict[str, int], *, needed: int) -> list[ContentEntity]:
        under_cap = [asset for asset in self.entities if counts.get(asset.entity_id, 0) < 2]
        if len(under_cap) >= needed:
            return sorted(under_cap, key=lambda a: (counts.get(a.entity_id, 0), a.entity_id))
        # Documented fallback for too-small pools: keep generating with the least-used names.
        return sorted(self.entities, key=lambda a: (counts.get(a.entity_id, 0), a.entity_id))


def _questions_per_day(settings: Mapping[str, Any], template_count: int) -> int:
    raw = _stocks_config(settings).get("questions_per_day")
    n = _optional_positive_int(raw)
    if n is None:
        n = max(50, template_count)
    return max(template_count, n)


def _stocks_config(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = settings.get("stocks")
    return raw if isinstance(raw, Mapping) else {}


def _filter_rows_by_min_start(
    rows: Sequence[StockQuestionRow],
    window_start: str,
) -> list[StockQuestionRow]:
    min_start = parse_date(window_start)
    return [row for row in rows if parse_date(row.start_date) >= min_start]


def _effective_max_generated_questions(settings: Mapping[str, Any]) -> int | None:
    """Total row cap for stock generation.

    ``stocks.max_generated_questions`` overrides the global ``max_generated_questions``
    (the same key the UI / LLM pipeline use) so one control caps output either way.
    """

    stocks_cfg = _stocks_config(settings)
    n = _optional_positive_int(stocks_cfg.get("max_generated_questions"))
    if n is not None:
        return n
    raw = settings.get("max_generated_questions")
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _optional_positive_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _template_sort_key(template: QuestionTemplate) -> tuple[int, int, str]:
    timeframe_order = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3}
    tf = _timeframe(template)
    # Gainer/loser long-horizon MC templates come after single-asset templates.
    variety_weight = 1 if "biggest" in template.id and tf in {"monthly", "quarterly"} else 0
    return (variety_weight, timeframe_order.get(tf, 0), template.id)


def _timeframe(template: QuestionTemplate) -> str:
    if template.timeframe:
        return template.timeframe.strip().lower()
    lowered = template.id.lower()
    for value in ("daily", "weekly", "monthly", "quarterly"):
        if value in lowered:
            return value
    return "daily"


def _needs_option_assets(template: QuestionTemplate) -> bool:
    return "{ASSET_1}" in template.answer_options


def _fill_placeholders(
    text: str,
    question_date: date,
    selected: Mapping[str, ContentEntity],
) -> str:
    month_year = question_date.strftime("%B %Y")
    values: dict[str, str] = {
        "DATE": question_date.isoformat(),
        "MONTH": month_year,
        "QUARTER": str(quarter_number(question_date)),
        "YEAR": str(question_date.year),
    }
    for key, asset in selected.items():
        values[key] = asset.display_name

    out = text
    # The client template CSV contains both "{MONTH}" and "{MONTH} {YEAR}" forms.
    out = out.replace("{MONTH} {YEAR}", month_year)
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out

