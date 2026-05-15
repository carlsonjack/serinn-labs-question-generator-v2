"""Typed contracts for the input parser layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SourceRole(str, Enum):
    """Cross-vertical roles a source file can play."""

    EVENT_SOURCE = "event_source"
    ENTITY_SOURCE = "entity_source"
    METRIC_SOURCE = "metric_source"
    REFERENCE_SOURCE = "reference_source"
    UNKNOWN = "unknown"


class ValidationSeverity(str, Enum):
    """Severity levels for parser issues."""

    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationIssue:
    """A structured issue discovered during detection or normalization."""

    code: str
    message: str
    severity: ValidationSeverity
    file_path: str | None = None
    source_role: SourceRole | None = None
    field_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class InputProfile:
    """Persisted detection metadata for reproducible imports."""

    profile_name: str
    category_key: str
    file_pattern: str
    source_role: SourceRole
    format_name: str
    sheet_name: str | None
    header_row_index: int
    field_mappings: dict[str, str]
    fingerprint: str | None = None
    confidence: float | None = None
    normalizer_options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_role"] = self.source_role.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InputProfile":
        return cls(
            profile_name=data["profile_name"],
            category_key=data["category_key"],
            file_pattern=data["file_pattern"],
            source_role=SourceRole(data["source_role"]),
            format_name=data["format_name"],
            sheet_name=data.get("sheet_name"),
            header_row_index=int(data["header_row_index"]),
            field_mappings=dict(data.get("field_mappings", {})),
            fingerprint=data.get("fingerprint"),
            confidence=data.get("confidence"),
            normalizer_options=dict(data.get("normalizer_options", {})),
        )


@dataclass
class DetectedFile:
    """A raw input file after structure detection."""

    file_path: Path
    format_name: str
    source_role: SourceRole
    sheet_name: str | None
    header_row_index: int
    columns: list[str]
    field_mappings: dict[str, str]
    confidence: float
    records: list[dict[str, Any]]
    profile_used: InputProfile | None = None


@dataclass
class NormalizedEvent:
    """Canonical scheduled content unit consumed by existing event templates."""

    event_id: str
    home_team: str
    away_team: str
    event_datetime: str
    subcategory: str
    event_display: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentEntity:
    """Canonical entity/watchlist record for non-matchup verticals."""

    entity_id: str
    display_name: str
    source_role: SourceRole = SourceRole.ENTITY_SOURCE
    entity_type: str = "entity"
    topic_import_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlayerStatRecord:
    """Canonical sports metric record for entity-stat templates."""

    player_name: str
    team: str
    source_team: str
    stat_values: dict[str, float]
    source_sheet: str | None
    row_number: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParserResult:
    """Standard return envelope for file parsers."""

    data: list[Any]
    warnings: list[ValidationIssue] = field(default_factory=list)
    errors: list[ValidationIssue] = field(default_factory=list)
    profile_used: InputProfile | None = None


@dataclass
class NormalizedBundle:
    """All normalized parser outputs needed by downstream stages."""

    events: list[NormalizedEvent] = field(default_factory=list)
    entities: list[ContentEntity] = field(default_factory=list)
    player_stats: list[PlayerStatRecord] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    profiles: list[InputProfile] = field(default_factory=list)


@dataclass
class MatchupSplitSpec:
    """How to split one matchup column into canonical team fields."""

    source_column: str
    delimiter_pattern: str = " v "
    left_team_field: str = "home_team"
    right_team_field: str = "away_team"


@dataclass
class EventDatetimeSpec:
    """How to build an event datetime."""

    datetime_column: str | None = None
    date_column: str | None = None
    time_column: str | None = None
    timezone: str | None = None


@dataclass
class EventIdSpec:
    """How to build a stable event id when no event id column exists."""

    source_columns: list[str] = field(default_factory=list)
    strategy: str = "slug"


@dataclass
class SourceNormalizationSpec:
    """Declarative normalization rules for one configured input slot/source."""

    source_role: SourceRole
    file_pattern: str
    sheet_name: str | None = None
    header_row_index: int | None = None
    field_mappings: dict[str, str] = field(default_factory=dict)
    metric_mappings: dict[str, str] = field(default_factory=dict)
    metadata_mappings: dict[str, str] = field(default_factory=dict)
    matchup_split: MatchupSplitSpec | None = None
    event_datetime: EventDatetimeSpec | None = None
    event_id: EventIdSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_role"] = self.source_role.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceNormalizationSpec":
        matchup = data.get("matchup_split")
        event_datetime = data.get("event_datetime")
        event_id = data.get("event_id")
        return cls(
            source_role=SourceRole(data["source_role"]),
            file_pattern=str(data.get("file_pattern") or ""),
            sheet_name=data.get("sheet_name"),
            header_row_index=(
                int(data["header_row_index"])
                if data.get("header_row_index") is not None
                else None
            ),
            field_mappings=dict(data.get("field_mappings") or {}),
            metric_mappings=dict(data.get("metric_mappings") or {}),
            metadata_mappings=dict(data.get("metadata_mappings") or {}),
            matchup_split=(
                MatchupSplitSpec(**matchup) if isinstance(matchup, dict) else None
            ),
            event_datetime=(
                EventDatetimeSpec(**event_datetime)
                if isinstance(event_datetime, dict)
                else None
            ),
            event_id=EventIdSpec(**event_id) if isinstance(event_id, dict) else None,
        )


@dataclass
class NormalizationSpec:
    """Approved declarative normalizer for one package."""

    package_key: str
    sources: dict[str, SourceNormalizationSpec]
    version: int = 1
    shape_signature: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "package_key": self.package_key,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            "shape_signature": self.shape_signature,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NormalizationSpec":
        sources_raw = data.get("sources") or {}
        if not isinstance(sources_raw, dict):
            raise ValueError("NormalizationSpec.sources must be a mapping")
        return cls(
            version=int(data.get("version") or 1),
            package_key=str(data.get("package_key") or ""),
            sources={
                str(slot_id): SourceNormalizationSpec.from_dict(source_data)
                for slot_id, source_data in sources_raw.items()
                if isinstance(source_data, dict)
            },
            shape_signature=dict(data.get("shape_signature") or {}),
            notes=str(data.get("notes") or ""),
        )

