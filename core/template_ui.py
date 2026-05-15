"""UI-facing descriptions, previews, and package matching for templates."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from core.template_config.schema import QuestionTemplate

_PACKAGE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def normalize_template_package(value: str) -> str:
    """Normalize package/subcategory labels for case-insensitive matching."""

    return _PACKAGE_TOKEN_RE.sub("", (value or "").strip().lower())


def package_aliases_for_settings(
    settings: Mapping[str, Any],
    package_key: str,
) -> list[str]:
    """Return template labels that should match ``package_key``.

    ``inputs.package_aliases`` accepts either a single string or a list of strings:

    ``{"formula_one": "F1"}`` or ``{"formula_one": ["F1", "Formula 1"]}``.
    """

    aliases_root = ((settings.get("inputs") or {}).get("package_aliases")) or {}
    if not isinstance(aliases_root, Mapping):
        return []
    direct = aliases_root.get(package_key)
    if direct is None:
        pkg_norm = normalize_template_package(package_key)
        for raw_key, raw_value in aliases_root.items():
            if normalize_template_package(str(raw_key)) == pkg_norm:
                direct = raw_value
                break
    if direct is None:
        return []
    if isinstance(direct, str):
        return [direct]
    if isinstance(direct, Iterable):
        return [str(item) for item in direct if str(item).strip()]
    return []


def _package_match_labels(package_key: str, aliases: Iterable[str] | None) -> set[str]:
    return {
        normalize_template_package(value)
        for value in [package_key, *(aliases or [])]
        if normalize_template_package(value)
    }


def template_matches_package(
    template: QuestionTemplate,
    package_key: str,
    aliases: Iterable[str] | None = None,
) -> bool:
    """Whether ``template`` belongs to ``package_key`` under normalized matching."""

    labels = _package_match_labels(package_key, aliases)
    if not labels:
        return False
    return normalize_template_package(template.subcategory) in labels


def filter_templates_for_package(
    templates: Iterable[QuestionTemplate],
    package_key: str,
    aliases: Iterable[str] | None = None,
) -> list[QuestionTemplate]:
    """Return templates whose subcategory matches the selected input package."""

    return sorted(
        [t for t in templates if template_matches_package(t, package_key, aliases)],
        key=lambda t: t.id,
    )


def humanize_package_key(package_key: str) -> str:
    """Turn an ``inputs.files`` package key into a short display label."""

    pkg = (package_key or "").strip()
    if not pkg:
        return "Content"
    if "_" in pkg or "-" in pkg:
        return pkg.replace("-", " ").replace("_", " ").title()
    if len(pkg) <= 4:
        return pkg.upper()
    return pkg[:1].upper() + pkg[1:]


def infer_subcategory_for_package(
    templates: Iterable[QuestionTemplate],
    package_key: str,
    fallback: str = "",
    aliases: Iterable[str] | None = None,
) -> str:
    """Return the UI/display subcategory label for the selected package.

    The label follows the **input package** (and configured aliases), not the
    first matching template by id — otherwise ``music-*`` templates sorted before
    ``movie-*`` could show *Music* while *movies* is selected.
    """

    alias_list = [str(a).strip() for a in (aliases or []) if str(a).strip()]
    if len(alias_list) == 1:
        return alias_list[0]

    matched = filter_templates_for_package(templates, package_key, aliases)
    if matched:
        counts = Counter(t.subcategory for t in matched)
        if len(counts) == 1:
            return next(iter(counts))
        top_subcat, top_n = counts.most_common(1)[0]
        if top_n / len(matched) >= 0.9:
            return top_subcat
        return humanize_package_key(package_key)

    raw = (fallback or "").strip()
    if raw:
        return raw
    return humanize_package_key(package_key)


def _preview_question_text(t: QuestionTemplate) -> str:
    """Short preview of template wording (placeholders kept literal)."""
    q = (t.question or "").strip()
    if len(q) > 220:
        return q[:217] + "…"
    return q


def _preview_answer_options(t: QuestionTemplate) -> str:
    ao = (t.answer_options or "").strip()
    if len(ao) > 120:
        return ao[:117] + "…"
    return ao


def explain_template(t: QuestionTemplate) -> list[str]:
    """Human-readable bullets for the UI when a template is selected."""

    lines: list[str] = []
    if t.question_family == "event":
        lines.append(
            "One output row per scheduled content unit in your date window for each "
            "enabled event-style template. Dates and answer options are taken from "
            "your inputs; the model only polishes the question wording."
        )
        if t.answer_type == "yes_no":
            lines.append('Answers are fixed to "Yes" / "No".')
        else:
            lines.append(
                "Answer options are built from the input data, not invented by the model."
            )
        if t.line is not None:
            lines.append(
                f"This template uses a numeric line ({t.line}) in the prompt; "
                "thresholds are still enforced in code from config."
            )
    elif t.question_family == "entity_stat":
        lines.append(
            "One output row per content unit that has enough entity metrics. Answer choices "
            "are only entities returned from your input files — the model does not invent names."
        )
        if t.stat_column:
            lines.append(
                f"Entities are ranked by the `{t.stat_column}` column in metrics; "
                f"top {t.top_n_per_team or '?'} per side are offered as options."
            )
    else:
        lines.append(
            "One deterministic output row per normalized content entity, pair, or configured "
            "static option set. Placeholders are filled from the approved normalizer profile."
        )

    if t._comment:
        lines.append(f"Author note: {t._comment}")

    return lines


def template_to_ui_dict(t: QuestionTemplate, *, enabled: bool) -> dict[str, Any]:
    """Serialize a template for the Flask UI (preview + explainer)."""

    return {
        "id": t.id,
        "subcategory": t.subcategory,
        "enabled": enabled,
        "question_family": t.question_family,
        "answer_type": t.answer_type,
        "priority": t.priority,
        "preview_question": _preview_question_text(t),
        "preview_answer_options": _preview_answer_options(t),
        "line": t.line,
        "stat_column": t.stat_column,
        "top_n_per_team": t.top_n_per_team,
        "requires_entities": t.requires_entities,
        "comment": t._comment or "",
        "explainer": explain_template(t),
    }
