"""AI-assisted proposal of declarative normalization specs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from openai import BadRequestError, OpenAI
from pydantic import BaseModel, Field

from .stat_keys import stat_storage_key
from .package_options import COMPETITION_FORMAT_FIELD, COMPETITION_FORMAT_TEAM
from .contracts import (
    EventDatetimeSpec,
    EventIdSpec,
    MatchupSplitSpec,
    NormalizationSpec,
    SourceNormalizationSpec,
    SourceRole,
)
from .declarative import validate_normalization_spec
from .detector import workbook_snapshot
from core.template_ui import normalize_template_package

from core.input_slots import present_files_map

from .service import _merged_file_role_map


class MatchupSplitProposal(BaseModel):
    source_column: str
    delimiter_pattern: str = r"\s+v\s+|\s+vs\.?\s+|\s+@\s+"
    left_team_field: str = "home_team"
    right_team_field: str = "away_team"


class EventDatetimeProposal(BaseModel):
    datetime_column: Optional[str] = None
    date_column: Optional[str] = None
    time_column: Optional[str] = None
    timezone: Optional[str] = None


class EventIdProposal(BaseModel):
    source_columns: List[str] = Field(default_factory=list)
    strategy: str = "slug"


class SourceSpecProposal(BaseModel):
    source_role: str
    file_pattern: str
    sheet_name: Optional[str] = None
    header_row_index: Optional[int] = None
    field_mappings: Dict[str, str] = Field(default_factory=dict)
    metric_mappings: Dict[str, str] = Field(default_factory=dict)
    metadata_mappings: Dict[str, str] = Field(default_factory=dict)
    matchup_split: Optional[MatchupSplitProposal] = None
    event_datetime: Optional[EventDatetimeProposal] = None
    event_id: Optional[EventIdProposal] = None


class NormalizationSpecProposal(BaseModel):
    package_key: str
    sources: Dict[str, SourceSpecProposal]
    notes: str = ""


_SYSTEM_PROMPT = """\
You propose declarative normalization specs for question generation.
Map uploaded workbook snapshots into canonical records, but do not invent data.
Return only the structured schema.

Canonical event fields:
- event_id (optional if you provide event_id source_columns)
- home_team
- away_team
- event_date/event_time or event_datetime
- event_display (optional)

Canonical player metric fields:
- player_name
- team (optional for field competitions such as golf — omit when rankings have no team column)
- metric_mappings: stat key -> numeric column

Field competitions (golf, F1-style calendars):
- Use competition_format "field" when the schedule has tournament/event rows without home/away teams.
- Map event_date (or start_date) and event_name/event_display; do not invent home_team/away_team or matchup_split.
- Metric sources may omit team when players are ranked globally (e.g. world rankings).

Canonical content/entity fields for entertainment, markets, and other watchlists:
- entity_name for a generic named item
- title for releases such as albums, movies, TV shows, books, or games
- release_date/premiere_date/air_date as release_date when present
- artist, director, platform, network, studio, label, genre, content_type as metadata
- topic_import_id when present

Use matchup_split when a column like Matchup contains strings such as
"Mexico v South Africa" or "Team A vs Team B". Preserve useful extra columns
like Group, Venue, City, Archetype, or Star Power in metadata_mappings.
For content release lists, use source_role "entity_source"; map the primary title
column to title, the date column to release_date, and preserve descriptive columns
in metadata_mappings. Release Date cells may look like plain dates ("June 4, 2026"),
ISO strings, or marketing ranges such as "Daily – Jun 11–Jul 19, 2026" (Unicode dashes,
episode windows). Always map that column to field key release_date anyway—the
executor keeps the raw text; downstream parsing uses the **start** date of a range.
Use uppercase stat keys with underscores, e.g. GOAL_PROBABILITY.
"""


def _complete_normalization_proposal(
    openai_client: OpenAI, model: str, user_text: str
) -> NormalizationSpecProposal:
    """Call Chat Completions with non-strict JSON schema.

    ``beta.chat.completions.parse`` enables strict structured outputs, which
    rejects schemas where some objects use ``additionalProperties`` (e.g. dict
    fields) without a full ``properties`` + ``required`` layout. We validate
    with Pydantic after the model responds instead.
    """

    schema = NormalizationSpecProposal.model_json_schema()
    response_format: dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "NormalizationSpecProposal",
            "schema": schema,
            "strict": False,
        },
    }
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
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
        raise RuntimeError(f"Model refused: {refusal}")
    content = msg.content
    if not content:
        raise RuntimeError("Model returned empty content for normalization proposal")
    return NormalizationSpecProposal.model_validate_json(content)


def propose_normalization_spec(
    settings: Mapping[str, Any],
    *,
    category_key: str,
    input_dir: Path,
    file_config: Mapping[str, str],
    client: Optional[OpenAI] = None,
    use_ai: bool = True,
) -> tuple[NormalizationSpec, list[dict[str, Any]]]:
    """Build a proposed NormalizationSpec and the workbook snapshots used."""

    snapshots = _snapshots_for_package(settings, category_key, input_dir, file_config)
    if _is_stocks_package(category_key) or not use_ai or not settings.get("openai_api_key"):
        return _heuristic_spec(category_key, snapshots), snapshots

    openai_client = client or OpenAI(api_key=str(settings.get("openai_api_key") or ""))
    model = str(settings.get("model") or "gpt-5.4")
    user_text = json.dumps(
        {"package_key": category_key, "workbook_snapshots": snapshots},
        default=str,
    )
    parsed = _complete_normalization_proposal(openai_client, model, user_text)
    spec = _proposal_to_spec(parsed)
    spec.shape_signature = _shape_signature(snapshots)
    spec.competition_format = _infer_competition_format(category_key, snapshots)
    issues = validate_normalization_spec(spec)
    errors = [issue for issue in issues if issue.severity.value == "error"]
    if errors:
        detail = "; ".join(issue.message for issue in errors)
        raise ValueError(f"AI normalization spec failed validation: {detail}")
    return spec, snapshots


def uses_ai_normalization(settings: Mapping[str, Any], *, category_key: str, requested: bool) -> bool:
    """Whether a package should use the AI declarative-profile proposer."""

    return bool(requested and settings.get("openai_api_key") and not _is_stocks_package(category_key))


def _snapshots_for_package(
    settings: Mapping[str, Any],
    category_key: str,
    input_dir: Path,
    file_config: Mapping[str, str],
) -> list[dict[str, Any]]:
    present = present_files_map(input_dir, file_config)
    role_map = _merged_file_role_map(settings, category_key, dict(present))
    snapshots: list[dict[str, Any]] = []
    for slot_id, filename in sorted(present.items()):
        snap = workbook_snapshot(input_dir / filename)
        snap["slot_id"] = slot_id
        role_name = role_map.get(slot_id, SourceRole.UNKNOWN.value)
        if _is_stocks_package(category_key) and _looks_like_stock_snapshot(snap):
            role_name = SourceRole.ENTITY_SOURCE.value
        snap["source_role"] = role_name
        snapshots.append(snap)
    return snapshots


def _heuristic_spec(category_key: str, snapshots: list[dict[str, Any]]) -> NormalizationSpec:
    sources: dict[str, SourceNormalizationSpec] = {}
    for snap in snapshots:
        slot_id = str(snap["slot_id"])
        source_role = SourceRole(str(snap.get("source_role") or SourceRole.UNKNOWN.value))
        first_sheet = (snap.get("sheets") or [{}])[0]
        field_mappings = dict(first_sheet.get("field_mappings") or {})
        columns = [str(c) for c in first_sheet.get("columns") or []]

        if source_role == SourceRole.UNKNOWN and _looks_like_content_fields(field_mappings):
            source_role = SourceRole.ENTITY_SOURCE

        if source_role == SourceRole.EVENT_SOURCE:
            source = _heuristic_event_source(snap, first_sheet, field_mappings, columns)
        elif source_role == SourceRole.METRIC_SOURCE:
            source = _heuristic_metric_source(snap, first_sheet, field_mappings, columns)
        elif source_role == SourceRole.ENTITY_SOURCE:
            source = _heuristic_entity_source(snap, first_sheet, field_mappings, columns)
        else:
            source = SourceNormalizationSpec(
                source_role=source_role,
                file_pattern=str(snap["filename"]),
                sheet_name=first_sheet.get("sheet_name"),
                header_row_index=first_sheet.get("header_row_index"),
                field_mappings=field_mappings,
                metadata_mappings=_metadata_mappings(columns, set(field_mappings.values())),
            )
        sources[slot_id] = source

    return NormalizationSpec(
        package_key=category_key,
        sources=sources,
        shape_signature=_shape_signature(snapshots),
        notes="Generated by local heuristics; review before saving.",
        competition_format=_infer_competition_format(category_key, snapshots),
    )


def _is_stocks_package(category_key: str) -> bool:
    return normalize_template_package(category_key) == "stocks"


def _looks_like_stock_snapshot(snapshot: Mapping[str, Any]) -> bool:
    for sheet in snapshot.get("sheets") or []:
        fields = set((sheet.get("field_mappings") or {}).keys())
        if {"company_name", "ticker"} <= fields:
            return True
    return False


def _looks_like_content_fields(field_mappings: Mapping[str, str]) -> bool:
    fields = set(field_mappings)
    return bool(fields & {"title", "entity_name", "company_name", "ticker"})


def _heuristic_entity_source(
    snap: Mapping[str, Any],
    sheet: Mapping[str, Any],
    field_mappings: dict[str, str],
    columns: list[str],
) -> SourceNormalizationSpec:
    used = set(field_mappings.values())
    return SourceNormalizationSpec(
        source_role=SourceRole.ENTITY_SOURCE,
        file_pattern=str(snap["filename"]),
        sheet_name=sheet.get("sheet_name"),
        header_row_index=sheet.get("header_row_index"),
        field_mappings=field_mappings,
        metadata_mappings=_metadata_mappings(columns, used),
    )


def _heuristic_event_source(
    snap: Mapping[str, Any],
    sheet: Mapping[str, Any],
    field_mappings: dict[str, str],
    columns: list[str],
) -> SourceNormalizationSpec:
    matchup_col = _find_column(columns, {"matchup", "game", "fixture"})
    if not {"home_team", "away_team"} <= set(field_mappings):
        event_name_col = _find_column(columns, {"event_name", "event", "tournament"})
        date_col = field_mappings.get("event_date") or _find_column(
            columns, {"start_date", "date", "event_date"}
        )
        if event_name_col:
            field_mappings.setdefault("event_name", event_name_col)
            field_mappings.setdefault("event_display", event_name_col)
        if date_col:
            field_mappings.setdefault("event_date", date_col)
    event_datetime = EventDatetimeSpec(
        datetime_column=field_mappings.get("event_datetime"),
        date_column=field_mappings.get("event_date") or _find_column(columns, {"date"}),
        time_column=field_mappings.get("event_time") or _find_column(columns, {"time (est)", "time"}),
        timezone="America/New_York" if _find_column(columns, {"time (est)"}) else None,
    )
    event_id_columns = [
        c
        for c in [
            event_datetime.date_column,
            matchup_col,
            field_mappings.get("home_team"),
            field_mappings.get("away_team"),
        ]
        if c
    ]
    matchup = (
        MatchupSplitSpec(source_column=matchup_col, delimiter_pattern=r"\s+v\s+|\s+vs\.?\s+|\s+@\s+")
        if matchup_col and not {"home_team", "away_team"} <= set(field_mappings)
        else None
    )
    used = set(field_mappings.values()) | set(event_id_columns)
    if matchup_col:
        used.add(matchup_col)
    return SourceNormalizationSpec(
        source_role=SourceRole.EVENT_SOURCE,
        file_pattern=str(snap["filename"]),
        sheet_name=sheet.get("sheet_name"),
        header_row_index=sheet.get("header_row_index"),
        field_mappings=field_mappings,
        metadata_mappings=_metadata_mappings(columns, used),
        matchup_split=matchup,
        event_datetime=event_datetime,
        event_id=EventIdSpec(source_columns=event_id_columns),
    )


def _heuristic_metric_source(
    snap: Mapping[str, Any],
    sheet: Mapping[str, Any],
    field_mappings: dict[str, str],
    columns: list[str],
) -> SourceNormalizationSpec:
    if "player_name" not in field_mappings:
        player_col = _find_column(columns, {"player", "name"})
        if player_col:
            field_mappings["player_name"] = player_col
    metric_mappings: dict[str, str] = {}
    for column in columns:
        if column in set(field_mappings.values()):
            continue
        samples = [row.get(column) for row in sheet.get("sample_rows") or []]
        if any(_looks_numeric(v) for v in samples):
            metric_mappings[stat_storage_key(column)] = column
    used = set(field_mappings.values()) | set(metric_mappings.values())
    return SourceNormalizationSpec(
        source_role=SourceRole.METRIC_SOURCE,
        file_pattern=str(snap["filename"]),
        sheet_name=sheet.get("sheet_name"),
        header_row_index=sheet.get("header_row_index"),
        field_mappings=field_mappings,
        metric_mappings=metric_mappings,
        metadata_mappings=_metadata_mappings(columns, used),
    )


def _proposal_to_spec(proposal: NormalizationSpecProposal) -> NormalizationSpec:
    return NormalizationSpec(
        package_key=proposal.package_key,
        sources={
            slot_id: SourceNormalizationSpec.from_dict(_model_dict(source))
            for slot_id, source in proposal.sources.items()
        },
        notes=proposal.notes,
    )


def _model_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _metadata_mappings(columns: list[str], used_columns: set[str]) -> dict[str, str]:
    return {
        stat_storage_key(column).lower(): column
        for column in columns
        if column and column not in used_columns
    }


def _shape_signature(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(s["slot_id"]): {
            "filename": s["filename"],
            "sheets": [
                {
                    "sheet_name": sheet["sheet_name"],
                    "columns": sheet["columns"],
                    "header_row_index": sheet["header_row_index"],
                }
                for sheet in s.get("sheets", [])
            ],
        }
        for s in snapshots
    }


def _find_column(columns: list[str], names: set[str]) -> str | None:
    lowered = {column.strip().lower(): column for column in columns}
    for name in names:
        if name in lowered:
            return lowered[name]
    return None


def _looks_numeric(value: Any) -> bool:
    if value in ("", None):
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _infer_competition_format(category_key: str, snapshots: list[dict[str, Any]]) -> str:
    key = normalize_template_package(category_key)
    if key in {"golf", "f1", "pga"}:
        return COMPETITION_FORMAT_FIELD

    field_schedule = False
    field_metrics = False
    for snap in snapshots:
        role = str(snap.get("source_role") or "")
        sheets = snap.get("sheets") or [{}]
        sheet = sheets[0] if sheets else {}
        fm = set(sheet.get("field_mappings") or {})
        cols = {str(c).strip().lower() for c in sheet.get("columns") or []}

        if role == SourceRole.EVENT_SOURCE.value:
            has_label = bool({"event_name", "event_display"} & fm) or bool(
                {"event_name", "start_date"} <= cols
            )
            has_teams = {"home_team", "away_team"} <= fm or "matchup" in cols
            if has_label and not has_teams:
                field_schedule = True

        if role == SourceRole.METRIC_SOURCE.value:
            has_player = "player_name" in fm or "player" in cols
            has_team = "team" in fm or "team" in cols
            if has_player and not has_team:
                field_metrics = True

    if field_schedule and (field_metrics or len(snapshots) == 1):
        return COMPETITION_FORMAT_FIELD
    return COMPETITION_FORMAT_TEAM
