"""High-level entrypoints for category input normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from collections.abc import Sequence

from .base import CategoryNormalizer
from .contracts import DetectedFile, NormalizedBundle, SourceRole, ValidationIssue, ValidationSeverity
from .detector import inspect_file
from .declarative import execute_normalization_spec
from .profiles import load_normalization_spec, save_profile
from .registry import get_category_normalizer, list_registered_categories
from .season_merge import infer_merge_profile_options
from core.data_layout import resolve_inputs_directory
from core.template_ui import normalize_template_package, package_aliases_for_settings

# Register built-in category normalizers.
from .f1 import normalizer as _f1_normalizer  # noqa: F401
from .mlb import normalizer as _mlb_normalizer  # noqa: F401
from .stocks import normalizer as _stocks_normalizer  # noqa: F401


def _match_inputs_package(
    files_root: Mapping[str, Any],
    category_key: str,
) -> tuple[str | None, dict[str, Any]]:
    """Return the YAML storage key for ``category_key`` and its slot → filename map."""

    if not isinstance(files_root, dict):
        return None, {}
    ck = category_key.strip()
    if ck in files_root and isinstance(files_root[ck], dict):
        return ck, files_root[ck]
    lower = ck.lower()
    for k, v in files_root.items():
        if isinstance(k, str) and isinstance(v, dict) and k.lower() == lower:
            return k, v
    return None, {}


def _legacy_two_slot_shape(file_config: dict[str, Any]) -> bool:
    """MLB-style ``event_source`` + ``metric_source`` filenames."""

    return (
        isinstance(file_config, dict)
        and "event_source" in file_config
        and "metric_source" in file_config
    )


_SOURCE_ROLE_SLOT_IDS: frozenset[str] = frozenset(
    r.value for r in SourceRole if r != SourceRole.UNKNOWN
)

# Slot ids under ``inputs.files.<pkg>`` that are not literal SourceRole names can
# still resolve without ``inputs.file_roles`` via these aliases (values are
# SourceRole strings). Target *filenames* remain arbitrary operator-chosen names.
_SLOT_ID_ROLE_ALIASES: dict[str, str] = {
    "schedule": SourceRole.EVENT_SOURCE.value,
    "fixtures": SourceRole.EVENT_SOURCE.value,
    "calendar": SourceRole.EVENT_SOURCE.value,
    "games": SourceRole.EVENT_SOURCE.value,
    "stats": SourceRole.METRIC_SOURCE.value,
    "metrics": SourceRole.METRIC_SOURCE.value,
    "player_stats": SourceRole.METRIC_SOURCE.value,
    "roster": SourceRole.ENTITY_SOURCE.value,
    "entities": SourceRole.ENTITY_SOURCE.value,
    "entity_source": SourceRole.ENTITY_SOURCE.value,
    "asset_source": SourceRole.ENTITY_SOURCE.value,
    "assets": SourceRole.ENTITY_SOURCE.value,
    "watchlist": SourceRole.ENTITY_SOURCE.value,
    "releases": SourceRole.ENTITY_SOURCE.value,
    "release_list": SourceRole.ENTITY_SOURCE.value,
    "catalog": SourceRole.ENTITY_SOURCE.value,
    "content": SourceRole.ENTITY_SOURCE.value,
    "stock_list": SourceRole.ENTITY_SOURCE.value,
    "stocks": SourceRole.ENTITY_SOURCE.value,
    "reference": SourceRole.REFERENCE_SOURCE.value,
}


def _infer_role_for_slot(slot_id: str) -> str | None:
    """Map a slot id to a SourceRole string when ``inputs.file_roles`` omits it."""

    sid = str(slot_id).strip()
    if sid in _SOURCE_ROLE_SLOT_IDS:
        return sid
    return _SLOT_ID_ROLE_ALIASES.get(sid.lower())


def _merged_file_role_map(
    settings: Mapping[str, Any],
    matched_pkg_key: str,
    file_config: dict[str, Any],
) -> dict[str, str]:
    """Explicit ``inputs.file_roles`` entries win; other slots use name/alias inference."""

    explicit = dict(_file_roles_for_package(settings, matched_pkg_key) or {})
    out: dict[str, str] = {}
    for slot_id in file_config:
        sid = str(slot_id).strip()
        if not sid:
            continue
        chosen = (explicit.get(sid) or "").strip() or (_infer_role_for_slot(sid) or "")
        if normalize_template_package(matched_pkg_key) == "stocks" and sid.lower() == "metric_source":
            chosen = SourceRole.ENTITY_SOURCE.value
        if chosen:
            out[sid] = chosen
    return out


def _file_roles_for_package(
    settings: Mapping[str, Any],
    matched_pkg_key: str,
) -> dict[str, str] | None:
    roles_root = (settings.get("inputs") or {}).get("file_roles") or {}
    if not isinstance(roles_root, dict):
        return None
    mk = matched_pkg_key.strip()
    if mk in roles_root and isinstance(roles_root[mk], dict):
        return {str(k): str(v) for k, v in roles_root[mk].items()}
    lower = mk.lower()
    for k, v in roles_root.items():
        if isinstance(k, str) and isinstance(v, dict) and k.lower() == lower:
            return {str(sk): str(sv) for sk, sv in v.items()}
    return None


def _metric_sheet_terms(_settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Optional hook; default picks sheets whose name hints at season."""

    return ("2026",)


def _normalizer_key_for_package(
    settings: Mapping[str, Any],
    category_key: str,
) -> str:
    """Resolve the registered normalizer for a package key or one of its aliases."""

    known = {normalize_template_package(k): k for k in list_registered_categories()}
    direct = normalize_template_package(category_key)
    if direct in known:
        return known[direct]
    for alias in package_aliases_for_settings(settings, category_key):
        normalized = normalize_template_package(alias)
        if normalized in known:
            return known[normalized]
    return category_key.strip().lower()


def resolve_input_scan_jobs(
    settings: Mapping[str, Any],
    *,
    category_key: str,
    input_dir: Path,
    file_config: dict[str, Any],
    matched_pkg_key: str,
) -> tuple[list[tuple[Path, SourceRole, tuple[str, ...]]], list[ValidationIssue]]:
    """Build (path, role, sheet_terms) jobs for detection passes."""

    issues: list[ValidationIssue] = []
    jobs: list[tuple[Path, SourceRole, tuple[str, ...]]] = []

    if _legacy_two_slot_shape(file_config):
        jobs.append(
            (
                input_dir / str(file_config["event_source"]),
                SourceRole.EVENT_SOURCE,
                (),
            )
        )
        jobs.append(
            (
                input_dir / str(file_config["metric_source"]),
                SourceRole.METRIC_SOURCE,
                _metric_sheet_terms(settings),
            )
        )
        return jobs, issues

    role_map = _merged_file_role_map(settings, matched_pkg_key, file_config)
    if not role_map:
        issues.append(
            ValidationIssue(
                code="missing_file_roles",
                message=(
                    f"Package {matched_pkg_key!r}: could not resolve any slot to a SourceRole. "
                    "Use slot ids that match roles (event_source, metric_source, …), "
                    "common aliases (schedule, stats, …), add inputs.file_roles for this package, "
                    "or use the two-slot layout event_source + metric_source with any filenames."
                ),
                severity=ValidationSeverity.ERROR,
            )
        )
        return [], issues

    for slot_id, fname in sorted(file_config.items()):
        role_name = role_map.get(slot_id)
        if not role_name:
            issues.append(
                ValidationIssue(
                    code="missing_slot_role",
                    message=(
                        f"No SourceRole for slot {slot_id!r} under package {matched_pkg_key!r}. "
                        "Rename the slot to a role or alias (e.g. schedule, metric_source), "
                        "or set inputs.file_roles for this package."
                    ),
                    severity=ValidationSeverity.ERROR,
                )
            )
            continue
        try:
            role = SourceRole(str(role_name).strip())
        except ValueError:
            issues.append(
                ValidationIssue(
                    code="invalid_source_role",
                    message=f"Invalid SourceRole for slot {slot_id!r}: {role_name!r}.",
                    severity=ValidationSeverity.ERROR,
                )
            )
            continue
        terms = _metric_sheet_terms(settings) if role == SourceRole.METRIC_SOURCE else ()
        jobs.append((input_dir / str(fname), role, terms))

    return jobs, issues


def _resolve_category_normalizer_class(
    registry_ck: str,
    detected_files: Sequence[DetectedFile],
) -> tuple[type[CategoryNormalizer] | None, str | None]:
    """Resolve a registered normalizer, or fall back for MLB-shaped schedule+stats bundles."""

    try:
        return get_category_normalizer(registry_ck), None
    except KeyError:
        roles = {d.source_role for d in detected_files}
        if SourceRole.EVENT_SOURCE in roles and SourceRole.METRIC_SOURCE in roles:
            try:
                return get_category_normalizer("mlb"), None
            except KeyError:
                pass
        known = ", ".join(list_registered_categories()) or "<none>"
        return None, (
            f"No normalizer registered for {registry_ck!r}. Known categories: {known}. "
            "If your package is schedule + player stats with MLB-like columns, both sources "
            "must be present and the MLB normalizer runs automatically. For a single calendar "
            "workbook (e.g. F1-style), set inputs.package_aliases to map your package to `f1`, "
            "or register a dedicated normalizer for that sport."
        )


def load_normalized_bundle(
    settings: Mapping[str, Any],
    *,
    category_key: str = "mlb",
) -> NormalizedBundle:
    """Load, detect, and normalize the configured inputs for one category."""

    registry_ck = _normalizer_key_for_package(settings, category_key)
    input_dir = resolve_inputs_directory(settings)
    files_root = (settings.get("inputs") or {}).get("files") or {}
    matched_pkg_key, file_config = _match_inputs_package(files_root, category_key)

    pre_issues: list[ValidationIssue] = []
    if matched_pkg_key is None or not isinstance(file_config, dict):
        pre_issues.append(
            ValidationIssue(
                code="unknown_input_package",
                message=(
                    f"No inputs.files entry for package {category_key!r}. "
                    f"Known packages: {sorted(str(k) for k in files_root.keys())}"
                ),
                severity=ValidationSeverity.ERROR,
            )
        )
        return NormalizedBundle(issues=pre_issues)

    jobs, role_issues = resolve_input_scan_jobs(
        settings,
        category_key=category_key,
        input_dir=input_dir,
        file_config=file_config,
        matched_pkg_key=matched_pkg_key,
    )
    pre_issues.extend(role_issues)

    issues: list[ValidationIssue] = []
    detected_files = []

    for path, role, sheet_terms in jobs:
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    code="missing_input_file",
                    message=f"Missing input file: {path}",
                    severity=ValidationSeverity.ERROR,
                    file_path=str(path),
                    source_role=role,
                )
            )
            continue
        detection = inspect_file(
            path,
            category_key=registry_ck,
            preferred_role=role,
            preferred_sheet_terms=sheet_terms,
        )
        if (
            role == SourceRole.METRIC_SOURCE
            and detection.detected_file.profile_used is not None
            and len(detection.sheet_detections) > 1
        ):
            detection.detected_file.profile_used.normalizer_options.update(
                infer_merge_profile_options(detection)
            )
        issues.extend(detection.issues)
        detected_files.append(detection.detected_file)
        if settings.get("parsing", {}).get("persist_profiles", True):
            if detection.detected_file.profile_used is not None:
                save_profile(detection.detected_file.profile_used)

    issues = [*pre_issues, *issues]

    if any(issue.severity == ValidationSeverity.ERROR for issue in issues):
        return NormalizedBundle(issues=issues)

    try:
        normalizer_cls = get_category_normalizer(registry_ck)
    except KeyError:
        spec = load_normalization_spec(matched_pkg_key)
        if spec is not None:
            bundle = execute_normalization_spec(spec, detected_files, settings)
            bundle.issues = [*issues, *bundle.issues]
            return bundle
        normalizer_cls, norm_err = _resolve_category_normalizer_class(
            registry_ck, detected_files
        )
    else:
        norm_err = None

    if normalizer_cls is None:
        return NormalizedBundle(
            issues=[
                ValidationIssue(
                    code="unknown_category_normalizer",
                    message=norm_err or f"No normalizer for {registry_ck!r}",
                    severity=ValidationSeverity.ERROR,
                )
            ]
        )

    try:
        bundle = normalizer_cls().normalize(detected_files, settings)
    except ValueError as exc:
        return NormalizedBundle(
            issues=[
                ValidationIssue(
                    code="normalizer_error",
                    message=str(exc),
                    severity=ValidationSeverity.ERROR,
                )
            ]
        )

    bundle.issues = [*issues, *bundle.issues]
    return bundle
