"""Flask application for the local web UI."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from core.config import load_settings, load_settings_disk_only, save_settings_yaml
from core.csv_export import DEFAULT_OUTPUT_DIR
from core.data_layout import resolve_inputs_directory
from core.input_date_range import infer_date_range_from_excel_paths
from core.input_slots import (
    clear_category_input_files,
    clear_unuploaded_category_input_files,
    get_files_map_for_category,
    get_inputs_category_key,
    iter_input_slots,
    list_input_categories,
    normalize_inputs_files,
    present_files_map,
    require_present_input_files,
    resolve_input_upload_filename,
    resolve_inputs_package_file_key,
    INPUT_DATA_SUFFIXES,
)
from core.parsers.ai_profile_builder import propose_normalization_spec, uses_ai_normalization
from core.parsers.contracts import NormalizationSpec, ValidationIssue, ValidationSeverity
from core.parsers.declarative import preview_normalization_spec, validate_normalization_spec
from core.parsers.detector import inspect_file
from core.parsers.profiles import save_normalization_spec
from core.parsers.service import load_normalized_bundle, resolve_input_scan_jobs
from core.pipeline import PipelineResult, pipeline_result_to_job_dict, run_pipeline
from core.template_config.loader import (
    index_template_json_paths_by_id,
    load_template_dir,
    resolve_templates_directory,
)
from core.template_config.schema import parse_template_dict
from core.resolution_date_spec import maybe_compile_resolution_for_template_data
from core.template_placeholder_mapper import normalize_template_for_upload
from core.template_ui import (
    filter_templates_for_package,
    humanize_package_key,
    infer_subcategory_for_package,
    normalize_template_package,
    package_aliases_for_settings,
    template_to_ui_dict,
)
from core.template_upload import parse_uploaded_template_file
from core.topic_import_catalog import append_topic_import_id_to_catalog, load_topic_import_ids_catalog

_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()
_JOBS: dict[str, "JobState"] = {}
_ACTIVE_RUN = False


def _is_safe_download_name(name: str) -> bool:
    if not name or name != Path(name).name:
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return bool(secure_filename(name) == name)


def _form_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class JobState:
    state: str  # queued | running | succeeded | failed
    phase: str = ""
    current_step: int = 0
    total_steps: int = 0
    error: str | None = None
    result: PipelineResult | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def _template_meta_for_package(
    settings: dict[str, Any], category_key: str
) -> tuple[list[dict[str, Any]], str]:
    """Return template cards and the display subcategory for ``category_key``."""

    tpl_dir = resolve_templates_directory(settings)
    templates = load_template_dir(tpl_dir)
    te = settings.get("templates_enabled") or {}
    aliases = package_aliases_for_settings(settings, category_key)
    matched = filter_templates_for_package(templates.values(), category_key, aliases)
    template_meta = [
        template_to_ui_dict(t, enabled=bool(te.get(t.id, True)))
        for t in matched
    ]
    subcategory_fallback = str(settings.get("subcategory") or "")
    if normalize_template_package(subcategory_fallback) != normalize_template_package(
        category_key
    ):
        subcategory_fallback = ""
    template_subcategory = infer_subcategory_for_package(
        templates.values(),
        category_key,
        fallback=subcategory_fallback or humanize_package_key(category_key),
        aliases=aliases,
    )
    return template_meta, template_subcategory


def _inputs_directory(settings: dict[str, Any]) -> Path:
    return resolve_inputs_directory(settings)


def _issue_to_api(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "file_path": issue.file_path,
        "source_role": issue.source_role.value if issue.source_role else None,
        "field_name": issue.field_name,
        "details": issue.details,
    }


def _detected_files_for_preview(
    settings: dict[str, Any],
    category_key: str,
    *,
    file_config: dict[str, str] | None = None,
) -> tuple[list[Any], list[ValidationIssue]]:
    input_dir = _inputs_directory(settings)
    if file_config is None:
        file_config = present_files_map(
            input_dir, get_files_map_for_category(settings, category_key)
        )
    jobs, issues = resolve_input_scan_jobs(
        settings,
        category_key=category_key,
        input_dir=input_dir,
        file_config=file_config,
        matched_pkg_key=category_key,
    )
    detected = []
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
        result = inspect_file(
            path,
            category_key=category_key.lower(),
            preferred_role=role,
            preferred_sheet_terms=sheet_terms,
        )
        issues.extend(result.issues)
        detected.append(result.detected_file)
    return detected, issues


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/")
    def index() -> str:
        settings = load_settings()
        ick = get_inputs_category_key(settings)
        template_meta, template_subcategory = _template_meta_for_package(settings, ick)
        input_slots = iter_input_slots(settings, ick)
        input_categories = list_input_categories(settings)
        if not input_categories:
            input_categories = [ick]
        inputs_block = settings.get("inputs") or {}
        files_root = inputs_block.get("files") if isinstance(inputs_block, dict) else {}
        if not isinstance(files_root, dict):
            files_root = {}
        return render_template(
            "index.html",
            settings=settings,
            template_meta=template_meta,
            output_dir=str(DEFAULT_OUTPUT_DIR),
            input_category_key=ick,
            input_categories=input_categories,
            input_slots=input_slots,
            inputs_files_map=files_root,
            template_subcategory=template_subcategory,
            topic_import_ids_catalog=load_topic_import_ids_catalog(),
        )

    @app.post("/api/inputs-files")
    def api_save_inputs_files() -> Any:
        """Replace ``inputs.files`` from JSON ``{ \"files\": { pkg: { slot: name } } }``."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        try:
            normalized = normalize_inputs_files(body.get("files"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        current = load_settings_disk_only()
        inputs_prev = current.get("inputs") or {}
        prev_cat = inputs_prev.get("category_key")
        keys = sorted(normalized.keys())
        if isinstance(prev_cat, str) and prev_cat.strip() in normalized:
            cat = prev_cat.strip()
        else:
            cat = keys[0]
        save_settings_yaml(
            {"_inputs_files": normalized, "inputs": {"category_key": cat}}
        )
        return jsonify(
            {
                "ok": True,
                "files": normalized,
                "category_key": cat,
            }
        )

    @app.post("/api/input-category")
    def api_save_input_category() -> Any:
        """Persist ``inputs.category_key`` when the UI input package changes."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        raw = str(body.get("category_key") or "").strip()
        if not raw:
            return jsonify({"error": "category_key is required"}), 400
        current = load_settings_disk_only()
        matched = resolve_inputs_package_file_key(current, raw)
        if matched is None:
            return jsonify({"error": f"Unknown input package: {raw!r}"}), 400
        prev = resolve_inputs_package_file_key(
            current, get_inputs_category_key(current)
        )
        cleared: list[str] = []
        if (
            prev
            and matched.lower() != prev.lower()
        ):
            input_dir = _inputs_directory(current)
            input_dir.mkdir(parents=True, exist_ok=True)
            cleared = clear_category_input_files(input_dir, current, matched)
        save_settings_yaml({"inputs": {"category_key": matched}})
        settings = load_settings()
        template_meta, template_subcategory = _template_meta_for_package(settings, matched)
        return jsonify(
            {
                "ok": True,
                "category_key": matched,
                "cleared_files": cleared,
                "template_meta": template_meta,
                "template_subcategory": template_subcategory,
            }
        )

    @app.post("/api/topic-import-ids/catalog")
    def api_append_topic_import_id_catalog() -> Any:
        """Append a custom topic import ID to ``config/topic_import_ids_catalog.json``."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        topic_id = str(body.get("topic_import_id") or body.get("id") or "").strip()
        label = str(body.get("label") or "").strip()
        try:
            result = append_topic_import_id_to_catalog(topic_id, label=label)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result)

    @app.get("/api/input-slots")
    def api_input_slots() -> Any:
        settings = load_settings()
        cat = (request.args.get("category") or "").strip() or get_inputs_category_key(
            settings
        )
        files_root = settings.get("inputs", {}).get("files") or {}
        if cat not in files_root:
            return jsonify({"error": f"Unknown input package: {cat!r}"}), 400
        slots = iter_input_slots(settings, cat)
        template_meta, template_subcategory = _template_meta_for_package(settings, cat)
        return jsonify(
            {
                "category_key": cat,
                "slots": slots,
                "template_meta": template_meta,
                "template_subcategory": template_subcategory,
            }
        )

    @app.post("/api/normalizer/analyze")
    def api_analyze_normalizer() -> Any:
        """Propose and preview a declarative normalizer profile for a package."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        settings = load_settings()
        cat = str(body.get("category_key") or get_inputs_category_key(settings)).strip()
        files_map = get_files_map_for_category(settings, cat)
        if not files_map:
            return jsonify({"error": f"No input files configured for package {cat!r}."}), 400
        input_dir = _inputs_directory(settings)
        present_error = require_present_input_files(input_dir, files_map)
        if present_error:
            return jsonify({"error": present_error}), 400
        present_map = present_files_map(input_dir, files_map)

        try:
            requested_ai = bool(body.get("use_ai", True))
            spec, snapshots = propose_normalization_spec(
                settings,
                category_key=cat,
                input_dir=input_dir,
                file_config=present_map,
                use_ai=requested_ai,
            )
            detected, detect_issues = _detected_files_for_preview(
                settings, cat, file_config=present_map
            )
            preview = preview_normalization_spec(spec, detected, settings)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 400

        preview["issues"] = [
            *[_issue_to_api(issue) for issue in detect_issues],
            *(preview.get("issues") or []),
        ]
        return jsonify(
            {
                "ok": True,
                "category_key": cat,
                "spec": spec.to_dict(),
                "snapshots": snapshots,
                "preview": preview,
                "used_ai": uses_ai_normalization(
                    settings,
                    category_key=cat,
                    requested=requested_ai,
                ),
            }
        )

    @app.post("/api/normalizer/preview")
    def api_preview_normalizer() -> Any:
        """Preview a submitted declarative normalizer profile without saving it."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        settings = load_settings()
        raw_spec = body.get("spec")
        if not isinstance(raw_spec, dict):
            return jsonify({"error": "spec is required"}), 400
        try:
            spec = NormalizationSpec.from_dict(raw_spec)
            detected, detect_issues = _detected_files_for_preview(
                settings, spec.package_key
            )
            preview = preview_normalization_spec(spec, detected, settings)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 400
        preview["issues"] = [
            *[_issue_to_api(issue) for issue in detect_issues],
            *(preview.get("issues") or []),
        ]
        return jsonify({"ok": True, "preview": preview})

    @app.post("/api/normalizer/save")
    def api_save_normalizer() -> Any:
        """Persist an approved declarative normalizer profile."""

        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400
        body = request.get_json(silent=True) or {}
        raw_spec = body.get("spec")
        if not isinstance(raw_spec, dict):
            return jsonify({"error": "spec is required"}), 400
        try:
            spec = NormalizationSpec.from_dict(raw_spec)
            issues = validate_normalization_spec(spec)
            errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
            if errors:
                return jsonify({"error": "; ".join(i.message for i in errors)}), 400
            path = save_normalization_spec(spec)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "path": str(path), "spec": spec.to_dict()})

    @app.post("/upload/templates")
    def upload_templates() -> Any:
        """Save one or more validated template files into ``templates_directory``."""

        settings = load_settings()
        tpl_dir = resolve_templates_directory(settings)
        tpl_dir.mkdir(parents=True, exist_ok=True)

        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            one = request.files.get("file")
            if one and one.filename:
                files = [one]
        if not files:
            return jsonify({"error": "No template file uploaded."}), 400

        replace_existing = _form_truthy(request.form.get("replace_existing"))

        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        staged: list[dict[str, Any]] = []
        staged_ids: set[str] = set()
        category_key = get_inputs_category_key(settings)
        content_entities = None
        try:
            content_entities = load_normalized_bundle(settings, category_key=category_key).entities
        except (FileNotFoundError, ValueError):
            content_entities = None

        for fh in files:
            name = fh.filename or ""
            try:
                raw_text = fh.read()
                blocks = parse_uploaded_template_file(name, raw_text)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                errors.append({"filename": name, "error": str(exc)})
                continue

            for block_index, data in enumerate(blocks, start=1):
                label = name if len(blocks) == 1 else f"{name} [block {block_index}]"
                try:
                    normalized = normalize_template_for_upload(
                        data,
                        settings,
                        category_key=category_key,
                        entities=content_entities,
                    )
                    data = normalized.data
                    warnings.extend(
                        {"filename": label, "warning": warning}
                        for warning in normalized.warnings
                    )
                    try:
                        data = maybe_compile_resolution_for_template_data(data, settings)
                    except (ValueError, RuntimeError) as exc:
                        errors.append({"filename": label, "error": str(exc)})
                        continue
                    parsed = parse_template_dict(data)
                except ValueError as exc:
                    errors.append({"filename": label, "error": str(exc)})
                    continue
                if parsed.id in staged_ids:
                    errors.append(
                        {
                            "filename": label,
                            "error": f"Duplicate template id in upload: {parsed.id!r}",
                        }
                    )
                    continue
                staged_ids.add(parsed.id)
                staged.append({"parsed": parsed, "label": label})

        disk_index = index_template_json_paths_by_id(tpl_dir)
        conflicts: list[dict[str, Any]] = []
        for item in staged:
            parsed = item["parsed"]
            safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", parsed.id).strip("_") or "template"
            target = tpl_dir / f"{safe_id}.json"
            existing = disk_index.get(parsed.id, [])
            others = [p for p in existing if p.resolve() != target.resolve()]
            if others:
                conflicts.append(
                    {
                        "template_id": parsed.id,
                        "save_as": target.name,
                        "existing_files": [p.name for p in others],
                    }
                )

        if conflicts and not replace_existing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "conflict": True,
                        "conflicts": conflicts,
                        "message": (
                            "These template ids already exist in other .json files. "
                            "Choose Cancel, or upload again with replace enabled to save "
                            f"as the canonical {conflicts[0].get('save_as', '*.json')} name(s) and remove the listed files."
                        ),
                    }
                ),
                409,
            )

        saved: list[dict[str, str]] = []
        unlink_resolved: set[Path] = set()
        for item in staged:
            parsed = item["parsed"]
            safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", parsed.id).strip("_") or "template"
            out_path = tpl_dir / f"{safe_id}.json"
            existing = disk_index.get(parsed.id, [])
            others = [p for p in existing if p.resolve() != out_path.resolve()]
            if replace_existing and others:
                for p in others:
                    unlink_resolved.add(p.resolve())
            with out_path.open("w", encoding="utf-8") as out_f:
                json.dump(parsed.to_dict(), out_f, indent=2, ensure_ascii=False)
                out_f.write("\n")
            saved.append({"id": parsed.id, "filename": out_path.name})

        for resolved in unlink_resolved:
            path = Path(resolved)
            if path.is_file() and path.suffix.lower() == ".json":
                try:
                    path.unlink()
                except OSError:
                    warnings.append(
                        {
                            "filename": path.name,
                            "warning": f"Could not remove duplicate template file {path.name}",
                        }
                    )

        disk = load_settings_disk_only()
        te = dict(disk.get("templates_enabled") or {})
        for item in saved:
            te[item["id"]] = True
        save_settings_yaml({"templates_enabled": te})

        return jsonify(
            {
                "ok": len(saved) > 0,
                "saved": saved,
                "errors": errors,
                "warnings": warnings,
                "replaced_duplicates": bool(replace_existing and unlink_resolved),
            }
        )

    @app.post("/upload")
    def upload() -> Any:
        settings = load_settings()
        input_dir = _inputs_directory(settings)
        cat = (request.form.get("category_key") or "").strip() or get_inputs_category_key(
            settings
        )
        files_map = get_files_map_for_category(settings, cat)
        if not files_map:
            return jsonify(
                {"error": f"No input files configured for package {cat!r}."}
            ), 400

        input_dir.mkdir(parents=True, exist_ok=True)

        uploaded_slot_ids: set[str] = set()
        pending: list[tuple[str, str, str, Any]] = []
        for slot_id, target_name in files_map.items():
            fh = request.files.get(slot_id)
            if fh is None or fh.filename == "":
                continue
            dest_name = resolve_input_upload_filename(target_name, fh.filename)
            if dest_name is None:
                allowed = ", ".join(sorted(INPUT_DATA_SUFFIXES))
                return jsonify(
                    {"error": f"Only {allowed} allowed: {fh.filename!r}"}
                ), 400
            uploaded_slot_ids.add(slot_id)
            pending.append((slot_id, target_name, dest_name, fh))

        cleared = clear_unuploaded_category_input_files(
            input_dir, files_map, uploaded_slot_ids
        )

        saved: list[dict[str, str]] = []
        files_updates: dict[str, str] = {}
        for slot_id, configured_name, dest_name, fh in pending:
            dest = input_dir / dest_name
            for suffix in INPUT_DATA_SUFFIXES:
                alt = input_dir / f"{Path(configured_name).stem}{suffix}"
                if alt.is_file() and alt != dest:
                    alt.unlink()
            fh.save(str(dest))
            saved.append({"slot_id": slot_id, "filename": dest_name})
            if dest_name != configured_name:
                files_updates[slot_id] = dest_name
        any_file = bool(saved)

        if files_updates:
            disk = load_settings_disk_only()
            inputs = dict(disk.get("inputs") or {})
            files_root = dict(inputs.get("files") or {})
            pkg_map = dict(files_root.get(cat) or {})
            pkg_map.update(files_updates)
            files_root[cat] = pkg_map
            save_settings_yaml({"inputs": {"files": files_root}})

        date_filter_auto: dict[str, Any] = {"applied": False}
        if saved:
            saved_paths = [input_dir / item["filename"] for item in saved]
            start_iso, end_iso = infer_date_range_from_excel_paths(saved_paths)
            if start_iso and end_iso:
                save_settings_yaml({"date_filter": {"start": start_iso, "end": end_iso}})
                date_filter_auto = {
                    "applied": True,
                    "start": start_iso,
                    "end": end_iso,
                }

        if not any_file:
            return jsonify(
                {
                    "error": "No files provided. Choose at least one file "
                    f"({', '.join(sorted(files_map.keys()))})."
                }
            ), 400

        return jsonify(
            {
                "ok": True,
                "category_key": cat,
                "saved": saved,
                "cleared_files": cleared,
                "date_filter_auto": date_filter_auto,
            }
        )

    @app.post("/run")
    def run() -> Any:
        global _ACTIVE_RUN
        if not request.is_json:
            return jsonify({"error": "Expected application/json"}), 400

        payload = request.get_json(silent=True) or {}
        with _LOCK:
            if _ACTIVE_RUN:
                return (
                    jsonify(
                        {
                            "error": "A generation job is already running. "
                            "Wait for it to finish before starting another."
                        }
                    ),
                    409,
                )

        try:
            updates = _build_settings_updates_from_payload(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        save_settings_yaml(updates)
        settings = load_settings()

        job_id = uuid.uuid4().hex
        with _LOCK:
            _ACTIVE_RUN = True
            _JOBS[job_id] = JobState(state="queued", phase="Queued")

        def work() -> None:
            global _ACTIVE_RUN
            try:
                with _LOCK:
                    st0 = _JOBS[job_id]
                    st0.state = "running"
                    st0.phase = "Starting pipeline"
                result_holder: list[PipelineResult] = []

                def progress(phase: str, cur: int, tot: int) -> None:
                    with _LOCK:
                        st = _JOBS.get(job_id)
                        if st:
                            st.phase = phase
                            st.current_step = cur
                            st.total_steps = tot

                result_holder.append(run_pipeline(settings, progress=progress))

                with _LOCK:
                    st = _JOBS[job_id]
                    st.result = result_holder[0]
                    st.state = "succeeded" if result_holder[0].success else "failed"
                    st.phase = "Done" if result_holder[0].success else "Failed"
                    if not result_holder[0].success and result_holder[0].message:
                        st.error = result_holder[0].message
                    st.payload = pipeline_result_to_job_dict(result_holder[0])
            except Exception as exc:  # noqa: BLE001
                with _LOCK:
                    st = _JOBS[job_id]
                    st.state = "failed"
                    st.error = str(exc)
                    st.phase = "Failed"
                    st.payload = {"success": False, "message": str(exc)}
            finally:
                with _LOCK:
                    _ACTIVE_RUN = False

        t = threading.Thread(target=work, daemon=True)
        t.start()

        return jsonify({"job_id": job_id})

    @app.get("/run/status/<job_id>")
    def run_status(job_id: str) -> Any:
        with _LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            return jsonify({"error": "Unknown job_id"}), 404

        body: dict[str, Any] = {
            "state": job.state,
            "phase": job.phase,
            "current_step": job.current_step,
            "total_steps": job.total_steps,
        }
        if job.error:
            body["error"] = job.error
        if job.state in ("succeeded", "failed"):
            body.update(job.payload)
        return jsonify(body)

    @app.get("/download/<filename>")
    def download(filename: str) -> Any:
        if not _is_safe_download_name(filename):
            abort(404)
        target = Path(DEFAULT_OUTPUT_DIR) / filename
        try:
            target.resolve().relative_to(Path(DEFAULT_OUTPUT_DIR).resolve())
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(
            str(DEFAULT_OUTPUT_DIR),
            filename,
            as_attachment=True,
        )

    return app


def _build_settings_updates_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map JSON body from the SPA into settings YAML updates."""

    updates: dict[str, Any] = {}

    if "topic_import_id" in payload:
        updates["topic_import_id"] = str(payload.get("topic_import_id") or "")

    if "subcategory" in payload:
        updates["subcategory"] = str(payload.get("subcategory") or "MLB")

    if "top_n_per_team" in payload:
        updates["top_n_per_team"] = int(payload.get("top_n_per_team") or 3)

    if "date_start" in payload or "date_end" in payload:
        base_df = dict(load_settings_disk_only().get("date_filter") or {})
        if "date_start" in payload:
            base_df["start"] = str(payload.get("date_start") or "")
        if "date_end" in payload:
            base_df["end"] = str(payload.get("date_end") or "")
        updates["date_filter"] = base_df

    if "templates_enabled" in payload and isinstance(payload["templates_enabled"], dict):
        updates["templates_enabled"] = {
            k: bool(v) for k, v in payload["templates_enabled"].items()
        }

    if "input_category_key" in payload:
        ick = str(payload.get("input_category_key") or "").strip()
        if ick:
            updates["inputs"] = {"category_key": ick}

    if "max_generated_questions" in payload:
        v = payload.get("max_generated_questions")
        if v is None or v == "":
            updates["max_generated_questions"] = None
        else:
            updates["max_generated_questions"] = int(v)

    if "_inputs_files" in payload and payload.get("_inputs_files") is not None:
        updates["_inputs_files"] = normalize_inputs_files(payload.get("_inputs_files"))

    return updates


app = create_app()
