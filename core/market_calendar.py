"""Small U.S. market calendar helpers for MVP stock generation."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class StockQuestionDates:
    start_date: str
    expiration_date: str
    resolution_date: str


def parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def iter_regular_trading_days(start: str | date, end: str | date) -> list[date]:
    """Return weekday trading days for MVP; holiday calendar can replace this later."""

    cur = parse_date(start)
    final = parse_date(end)
    days: list[date] = []
    while cur <= final:
        if is_regular_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def is_regular_trading_day(value: date) -> bool:
    return value.weekday() < 5


def first_regular_trading_day_of_week(value: date) -> date:
    cur = value - timedelta(days=value.weekday())
    while not is_regular_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def last_regular_trading_day_of_week(value: date) -> date:
    cur = value + timedelta(days=(4 - value.weekday()))
    while not is_regular_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def first_regular_trading_day_of_month(value: date) -> date:
    cur = value.replace(day=1)
    while not is_regular_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def last_regular_trading_day_of_month(value: date) -> date:
    _, last_day = calendar.monthrange(value.year, value.month)
    cur = value.replace(day=last_day)
    while not is_regular_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def quarter_number(value: date) -> int:
    return ((value.month - 1) // 3) + 1


def first_regular_trading_day_of_quarter(value: date) -> date:
    first_month = ((value.month - 1) // 3) * 3 + 1
    cur = value.replace(month=first_month, day=1)
    while not is_regular_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def last_regular_trading_day_of_quarter(value: date) -> date:
    last_month = ((value.month - 1) // 3) * 3 + 3
    _, last_day = calendar.monthrange(value.year, last_month)
    cur = value.replace(month=last_month, day=last_day)
    while not is_regular_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def first_calendar_day_of_quarter(value: date) -> date:
    first_month = ((value.month - 1) // 3) * 3 + 1
    return value.replace(month=first_month, day=1)


def last_calendar_day_of_first_month_of_quarter(value: date) -> date:
    first_month = ((value.month - 1) // 3) * 3 + 1
    _, last_day = calendar.monthrange(value.year, first_month)
    return value.replace(month=first_month, day=last_day)


def last_calendar_day_of_month(value: date) -> date:
    _, last_day = calendar.monthrange(value.year, value.month)
    return value.replace(day=last_day)


def last_calendar_day_of_quarter(value: date) -> date:
    last_month = ((value.month - 1) // 3) * 3 + 3
    _, last_day = calendar.monthrange(value.year, last_month)
    return value.replace(month=last_month, day=last_day)


def stock_question_dates(question_date: date, timeframe: str) -> StockQuestionDates:
    tf = (timeframe or "daily").strip().lower()
    if tf == "weekly":
        expiration = question_date - timedelta(days=question_date.weekday())
        start = expiration - timedelta(days=2)
        resolution = last_regular_trading_day_of_week(question_date) + timedelta(days=1)
    elif tf == "monthly":
        start = question_date.replace(day=1)
        expiration = question_date.replace(day=10)
        resolution = last_calendar_day_of_month(question_date) + timedelta(days=1)
    elif tf == "quarterly":
        start = first_calendar_day_of_quarter(question_date)
        expiration = last_calendar_day_of_first_month_of_quarter(question_date)
        resolution = last_calendar_day_of_quarter(question_date) + timedelta(days=1)
    else:
        start = question_date - timedelta(days=2)
        expiration = question_date
        resolution = question_date + timedelta(days=1)
    return StockQuestionDates(
        start_date=start.isoformat(),
        expiration_date=expiration.isoformat(),
        resolution_date=resolution.isoformat(),
    )

