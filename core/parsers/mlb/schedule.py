"""MLB schedule parsing and normalization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..base import InputParser
from ..contracts import ParserResult, SourceRole, ValidationIssue, ValidationSeverity, NormalizedEvent
from ..detector import inspect_file
from ..validators import validate_required_fields


class MlbScheduleParser(InputParser):
    """Parse schedule workbooks into canonical event records."""

    def __init__(self, settings: dict[str, Any], category_key: str = "mlb") -> None:
        super().__init__()
        self.settings = settings
        self.category_key = category_key
        self._detection = None

    def load(self, filepath: str | Path) -> "MlbScheduleParser":
        self._loaded_path = Path(filepath)
        self._detection = inspect_file(
            self._loaded_path,
            category_key=self.category_key,
            preferred_role=SourceRole.EVENT_SOURCE,
        )
        return self

    def normalize(self) -> ParserResult:
        if self._detection is None or self._loaded_path is None:
            raise RuntimeError("Schedule parser must load a file before normalize().")

        detected = self._detection.detected_file
        issues = list(self._detection.issues)
        issues.extend(
            validate_required_fields(
                file_path=str(detected.file_path),
                source_role=detected.source_role,
                field_mappings=detected.field_mappings,
                required_fields=[
                    "event_id",
                    "event_date",
                    "event_time",
                    "home_team",
                    "away_team",
                ],
            )
        )

        errors = [issue for issue in issues if issue.severity == ValidationSeverity.ERROR]
        warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]
        if errors:
            return ParserResult(
                data=[],
                warnings=warnings,
                errors=errors,
                profile_used=detected.profile_used,
            )

        filtered_events: list[NormalizedEvent] = []
        for row in detected.records:
            event_datetime = _combine_event_datetime(
                row[detected.field_mappings["event_date"]],
                row[detected.field_mappings["event_time"]],
            )
            if not _within_date_range(event_datetime, self.settings.get("date_filter", {})):
                continue

            filtered_events.append(
                NormalizedEvent(
                    event_id=str(row[detected.field_mappings["event_id"]]).strip(),
                    home_team=str(row[detected.field_mappings["home_team"]]).strip(),
                    away_team=str(row[detected.field_mappings["away_team"]]).strip(),
                    event_datetime=event_datetime.isoformat(),
                    subcategory="MLB",
                )
            )

        return ParserResult(
            data=filtered_events,
            warnings=warnings,
            errors=[],
            profile_used=detected.profile_used,
        )


def _combine_event_datetime(event_date: Any, event_time: Any) -> datetime:
    date_value = pd.to_datetime(event_date).date()
    time_text = str(event_time).strip()
    time_value = datetime.strptime(time_text, "%H:%M:%S").time()
    return datetime.combine(date_value, time_value)


def _within_date_range(event_datetime: datetime, date_filter: dict[str, Any]) -> bool:
    start = date_filter.get("start")
    end = date_filter.get("end")
    event_date = event_datetime.date()
    if start and event_date < pd.to_datetime(start).date():
        return False
    if end and event_date > pd.to_datetime(end).date():
        return False
    return True

