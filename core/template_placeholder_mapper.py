"""Upload-time normalization for content template placeholders."""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, List, Optional

from openai import BadRequestError, OpenAI
from pydantic import BaseModel, Field

from core.parsers.contracts import ContentEntity
from core.template_ui import normalize_template_package

_BRACKET_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")
_BRACE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")
_LETTERED_PLACEHOLDER_RE = re.compile(r"^(?P<prefix>[A-Z0-9]+)_(?P<letter>[A-Z])$")
_LETTERED_FIELD_RE = re.compile(r"^(?P<prefix>[A-Z0-9]+)_(?P<letter>[A-Z])_(?P<field>[A-Z0-9_]+)$")

_LETTER_INDEX = {chr(ord("A") + i): i + 1 for i in range(26)}
_FIELD_ALIASES: dict[str, str] = {
    "NAME": "ENTITY",
    "ENTITY_NAME": "ENTITY",
    "MOVIE": "ENTITY",
    "FILM": "ENTITY",
    "MOVIE_TITLE": "TITLE",
    "FILM_TITLE": "TITLE",
    "MOVIE_TITE": "TITLE",
    "TITE": "TITLE",
    "ALBUM_TITLE": "TITLE",
    "RELEASE_TITLE": "TITLE",
    "DATE": "RELEASE_DATE",
}
_BASE_CONTEXT_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "ENTITY",
        "TITLE",
        "MOVIE",
        "MOVIE_TITLE",
        "FILM",
        "FILM_TITLE",
        "ALBUM_OR_RELEASE",
        "ALBUM_OR_ARTIST",
        "RELEASE",
        "ARTIST",
        "STUDIO",
        "DIRECTOR",
        "PLATFORM",
        "NETWORK",
        "LABEL",
        "GENRE",
        "CONTENT_TYPE",
        "RELEASE_DATE",
        "PREMIERE_DATE",
        "AIR_DATE",
        "CHART_NAME",
        "TOUR_CHART_SOURCE",
        "YEAR",
    }
)
_MULTI_ENTITY_PREFIXES: frozenset[str] = frozenset({"ENTITY", "MOVIE", "FILM"})


class PlaceholderMappingSuggestion(BaseModel):
    placeholder: str
    canonical_placeholder: str
    target: str = ""
    confidence: float = 0.0
    reason: str = ""


class TemplateMappingProposal(BaseModel):
    generation_strategy: Optional[str] = None
    entity_count: Optional[int] = None
    mappings: List[PlaceholderMappingSuggestion] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PlaceholderContext:
    package_key: str
    placeholders: set[str]
    entity_count: int | None = None
    metadata_keys: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class TemplateNormalizationResult:
    data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def normalize_template_for_upload(
    data: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    category_key: str,
    entities: Sequence[ContentEntity] | None = None,
    client: OpenAI | None = None,
) -> TemplateNormalizationResult:
    """Normalize fuzzy content placeholders before template schema validation."""

    normalized = dict(data)
    if str(normalized.get("question_family") or "").strip() != "content":
        return TemplateNormalizationResult(normalized)

    context = build_placeholder_context(category_key, settings, entities=entities)
    placeholders = extract_placeholders_from_template(normalized)
    if not placeholders:
        return TemplateNormalizationResult(normalized)

    mappings, warnings = _heuristic_mappings(placeholders, context)
    unresolved = sorted(placeholders - set(mappings))
    if unresolved and settings.get("openai_api_key"):
        proposal = _ai_mapping_proposal(
            normalized,
            context,
            settings,
            client=client,
        )
        if proposal is not None:
            for suggestion in proposal.mappings:
                original = suggestion.placeholder.upper()
                canonical = suggestion.canonical_placeholder.upper()
                if suggestion.confidence >= 0.75 and _is_allowed_placeholder(canonical, context):
                    mappings[original] = {
                        "canonical_placeholder": canonical,
                        "target": suggestion.target,
                        "confidence": suggestion.confidence,
                        "source": "ai",
                        "reason": suggestion.reason,
                    }
            warnings.extend(proposal.warnings)
        unresolved = sorted(placeholders - set(mappings))

    if unresolved:
        available = ", ".join(sorted(context.placeholders)[:30])
        raise ValueError(
            "Unknown template placeholder(s): "
            + ", ".join(f"[{p}]" for p in unresolved)
            + f". Available placeholders include: {available}"
        )

    normalized = _apply_placeholder_mappings(normalized, mappings)
    strategy, entity_count = _infer_generation_strategy(mappings)
    if strategy:
        normalized["generation_strategy"] = strategy
        normalized["entity_count"] = entity_count
        if context.entity_count is not None and entity_count and context.entity_count < entity_count:
            raise ValueError(
                f"Template requires {entity_count} entities but the current input has "
                f"{context.entity_count} dated entities."
            )
    if mappings:
        normalized["placeholder_mappings"] = mappings
    warnings.extend(_mapping_warnings(mappings))
    return TemplateNormalizationResult(normalized, warnings)


def extract_placeholders_from_template(data: Mapping[str, Any]) -> set[str]:
    """Extract bracket and brace placeholders from the fillable template fields."""

    tokens: set[str] = set()
    for field_name in ("question", "answer_options"):
        value = data.get(field_name)
        if not isinstance(value, str):
            continue
        tokens.update(match.group(1).upper() for match in _BRACKET_PLACEHOLDER_RE.finditer(value))
        tokens.update(match.group(1).upper() for match in _BRACE_PLACEHOLDER_RE.finditer(value))
    return tokens


def build_placeholder_context(
    category_key: str,
    settings: Mapping[str, Any],
    *,
    entities: Sequence[ContentEntity] | None = None,
) -> PlaceholderContext:
    metadata_keys: set[str] = set()
    dated_entities = 0
    if entities is not None:
        for entity in entities:
            metadata_keys.update(str(key).upper() for key in entity.metadata)
            if any(entity.metadata.get(key) for key in ("release_date", "premiere_date", "air_date", "date")):
                dated_entities += 1

    placeholders = set(_BASE_CONTEXT_PLACEHOLDERS)
    placeholders.update(_field_to_placeholder(key) for key in metadata_keys)
    static = _content_static_values(settings)
    placeholders.update(str(key).upper() for key in static)
    for letter in _LETTER_INDEX:
        placeholders.update(
            {
                f"ENTITY_{letter}",
                f"TITLE_{letter}",
                f"MOVIE_{letter}",
                f"RELEASE_DATE_{letter}",
            }
        )
    return PlaceholderContext(
        package_key=normalize_template_package(category_key),
        placeholders=placeholders,
        entity_count=dated_entities if entities is not None else None,
        metadata_keys=metadata_keys,
    )


def _heuristic_mappings(
    placeholders: set[str],
    context: PlaceholderContext,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    mappings: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for placeholder in sorted(placeholders):
        canonical, confidence, reason = _heuristic_canonical_placeholder(placeholder, context)
        if canonical and _is_allowed_placeholder(canonical, context):
            mappings[placeholder] = {
                "canonical_placeholder": canonical,
                "target": _target_for_canonical(canonical),
                "confidence": confidence,
                "source": "heuristic",
                "reason": reason,
            }
        elif canonical:
            warnings.append(f"Ignored mapping [{placeholder}] -> [{canonical}] because the target is unavailable.")
    return mappings, warnings


def _heuristic_canonical_placeholder(
    placeholder: str,
    context: PlaceholderContext,
) -> tuple[str | None, float, str]:
    token = placeholder.upper()
    if token in _FIELD_ALIASES:
        return _FIELD_ALIASES[token], 0.98, "known field alias"

    lettered = _LETTERED_PLACEHOLDER_RE.match(token)
    if lettered:
        prefix = lettered.group("prefix")
        letter = lettered.group("letter")
        if prefix in {"MOVIE", "FILM"} or prefix == _package_singular(context.package_key):
            return f"ENTITY_{letter}", 0.95, "multi-entity option"
        if prefix == "ENTITY":
            return token, 1.0, "already supported"

    if token in context.placeholders:
        return token, 1.0, "already supported"

    lettered_field = _LETTERED_FIELD_RE.match(token)
    if lettered_field:
        prefix = lettered_field.group("prefix")
        letter = lettered_field.group("letter")
        field_name = _FIELD_ALIASES.get(lettered_field.group("field"), lettered_field.group("field"))
        if prefix in _MULTI_ENTITY_PREFIXES or prefix == _package_singular(context.package_key):
            return f"{field_name}_{letter}", 0.9, "multi-entity field"

    package_prefix = _package_singular(context.package_key)
    if package_prefix and token.startswith(f"{package_prefix}_"):
        suffix = token[len(package_prefix) + 1 :]
        if suffix in _FIELD_ALIASES:
            return _FIELD_ALIASES[suffix], 0.96, "package-prefixed alias"
        if suffix in context.placeholders:
            return suffix, 0.94, "package-prefixed canonical field"
        close = _closest_placeholder(suffix, context.placeholders)
        if close:
            return close, 0.82, "package-prefixed fuzzy match"

    close = _closest_placeholder(token, context.placeholders)
    if close:
        return close, 0.8, "fuzzy match"
    return None, 0.0, ""


def _ai_mapping_proposal(
    data: Mapping[str, Any],
    context: PlaceholderContext,
    settings: Mapping[str, Any],
    *,
    client: OpenAI | None = None,
) -> TemplateMappingProposal | None:
    openai_client = client or OpenAI(api_key=str(settings.get("openai_api_key") or ""))
    model = str(settings.get("model") or "gpt-5.4")
    schema = TemplateMappingProposal.model_json_schema()
    messages = [
        {
            "role": "system",
            "content": (
                "Map uploaded question-template placeholders to the provided canonical "
                "placeholder vocabulary. Do not invent source data. Return only JSON."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "template": data,
                    "available_placeholders": sorted(context.placeholders),
                    "package_key": context.package_key,
                    "entity_count": context.entity_count,
                },
                default=str,
            ),
        },
    ]
    try:
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "TemplateMappingProposal",
                        "schema": schema,
                        "strict": False,
                    },
                },  # type: ignore[arg-type]
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
        content = response.choices[0].message.content
        if not content:
            return None
        return TemplateMappingProposal.model_validate_json(content)
    except Exception:
        return None


def _apply_placeholder_mappings(
    data: dict[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    out = dict(data)
    for field_name in ("question", "answer_options"):
        value = out.get(field_name)
        if not isinstance(value, str):
            continue
        text = value
        for original, mapping in mappings.items():
            canonical = str(mapping.get("canonical_placeholder") or original).upper()
            if canonical == original:
                continue
            text = text.replace(f"[{original}]", f"[{canonical}]")
            text = text.replace(f"{{{original}}}", f"{{{canonical}}}")
        out[field_name] = text
    return out


def _infer_generation_strategy(
    mappings: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, int | None]:
    count = 0
    for mapping in mappings.values():
        canonical = str(mapping.get("canonical_placeholder") or "").upper()
        match = _LETTERED_PLACEHOLDER_RE.match(canonical)
        if match and match.group("prefix") in {"ENTITY", "TITLE", "MOVIE", "RELEASE_DATE"}:
            count = max(count, _LETTER_INDEX.get(match.group("letter"), 0))
    if count:
        return "multi_entity_choice", count
    return None, None


def _mapping_warnings(mappings: Mapping[str, Mapping[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for original, mapping in sorted(mappings.items()):
        canonical = str(mapping.get("canonical_placeholder") or original).upper()
        if original != canonical:
            warnings.append(f"Mapped [{original}] to [{canonical}].")
    return warnings


def _is_allowed_placeholder(placeholder: str, context: PlaceholderContext) -> bool:
    token = placeholder.upper()
    if token in context.placeholders:
        return True
    match = _LETTERED_PLACEHOLDER_RE.match(token)
    return bool(match and match.group("prefix") in {"ENTITY", "TITLE", "MOVIE", "RELEASE_DATE"})


def _target_for_canonical(canonical: str) -> str:
    token = canonical.upper()
    lettered = _LETTERED_PLACEHOLDER_RE.match(token)
    if lettered:
        index = _LETTER_INDEX[lettered.group("letter")] - 1
        field_name = lettered.group("prefix").lower()
        if field_name == "entity":
            field_name = "display_name"
        return f"selected_entities[{index}].{field_name}"
    return token.lower()


def _closest_placeholder(token: str, available: set[str]) -> str | None:
    matches = difflib.get_close_matches(token, sorted(available), n=1, cutoff=0.78)
    return matches[0] if matches else None


def _field_to_placeholder(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _package_singular(package_key: str) -> str:
    key = normalize_template_package(package_key)
    if key.endswith("ies"):
        return f"{key[:-3]}Y".upper()
    if key.endswith("s"):
        return key[:-1].upper()
    return key.upper()


def _content_static_values(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    content = settings.get("content")
    if not isinstance(content, Mapping):
        return {}
    static = content.get("static_values")
    return static if isinstance(static, Mapping) else {}
