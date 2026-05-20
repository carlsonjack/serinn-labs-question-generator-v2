#!/usr/bin/env python3
"""Analyze exact-duplicate removal for an MLB schedule run."""

from __future__ import annotations

import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.config import load_settings
from core.dedup import row_hash
from core.generation.deterministic_events import build_deterministic_questions
from core.generation.row_assembler import RowAssembler, build_event_string
from core.pipeline import build_prompt_items, is_template_enabled, run_pipeline
from core.parsers.declarative import execute_normalization_spec
from core.parsers.detector import inspect_file
from core.parsers.profiles import load_normalization_spec
from core.schema_validator import validate_rows
from core.template_config.loader import load_template_dir, resolve_templates_directory
from core.template_ui import filter_templates_for_package, package_aliases_for_settings


def main() -> None:
    schedule_src = Path(
        "/Users/jackcarlson/Downloads/Freelancing/Serinn/MLB 2026 Schedule.xlsx"
    )
    inputs_dir = REPO / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    shutil.copy2(schedule_src, inputs_dir / "schedule.xlsx")
    stats_path = inputs_dir / "stats.xlsx"
    if stats_path.is_file():
        stats_path.unlink()

    settings = load_settings()
    settings = dict(settings)
    settings["inputs"] = dict(settings.get("inputs") or {})
    settings["inputs"]["category_key"] = "mlb"

    schedule_path = inputs_dir / "schedule.xlsx"
    detected = inspect_file(
        schedule_path,
        category_key="mlb",
        preferred_role="event_source",
        preferred_sheet_terms=["MLB 2026"],
    )
    spec = load_normalization_spec("mlb")
    if spec is None:
        print("Missing declarative normalizer spec for mlb")
        sys.exit(1)
    bundle = execute_normalization_spec(spec, [detected.detected_file], settings)
    errors = [i for i in bundle.issues if i.severity.value == "error"]
    if errors:
        print("Bundle errors:")
        for e in errors:
            print(f"  - {e.message}")
        sys.exit(1)

    events = bundle.events
    print(f"Events in bundle (after date filter): {len(events)}")

    event_str_counts = Counter(build_event_string(e) for e in events)
    dup_event_strings = {k: v for k, v in event_str_counts.items() if v > 1}
    print(f"Duplicate event strings (same away vs home label): {len(dup_event_strings)}")
    if dup_event_strings:
        top = sorted(dup_event_strings.items(), key=lambda x: -x[1])[:10]
        print("  Top repeated event strings:")
        for label, count in top:
            print(f"    {count}x  {label}")

    event_id_by_string: dict[str, list[str]] = defaultdict(list)
    for e in events:
        event_id_by_string[build_event_string(e)].append(e.event_id)
    print("\nSample event_ids sharing one event string:")
    for label, count in sorted(dup_event_strings.items(), key=lambda x: -x[1])[:3]:
        ids = event_id_by_string[label][:5]
        print(f"  {label!r} ({count} rows): {ids}")

    tpl_dir = resolve_templates_directory(settings)
    all_templates = load_template_dir(tpl_dir)
    aliases = package_aliases_for_settings(settings, "mlb")
    active = [
        t
        for t in filter_templates_for_package(all_templates.values(), "mlb", aliases)
        if is_template_enabled(t.id, settings)
    ]
    print(f"\nEnabled MLB templates ({len(active)}):")
    for t in active:
        print(f"  - {t.id}: {t.question_family!r} — {t.question[:70]!r}")

    items = build_prompt_items(bundle, active, settings)
    print(f"\nPrompt items: {len(items)}")

    questions = build_deterministic_questions(items)
    assembler = RowAssembler(settings, category_key="mlb")
    rows = assembler.assemble_batch(questions, items)
    validation = validate_rows(rows)
    valid = validation.valid_rows
    print(f"Rows assembled: {len(rows)} | valid: {len(valid)} | invalid: {len(validation.invalid_rows)}")

    by_hash: dict[str, list] = defaultdict(list)
    for row in valid:
        by_hash[row_hash(row)].append(row)

    dup_groups = {h: rs for h, rs in by_hash.items() if len(rs) > 1}
    removed = sum(len(rs) - 1 for rs in dup_groups.values())
    kept = len(valid) - removed
    print(f"\nExact duplicate analysis (subcategory + event + question):")
    print(f"  Total valid rows: {len(valid)}")
    print(f"  Would remove: {removed}")
    print(f"  Would keep: {kept}")
    print(f"  Duplicate groups: {len(dup_groups)}")

    template_ids_by_group: Counter[str] = Counter()
    for rs in dup_groups.values():
        template_ids_by_group[len(rs)] += 1
    print("\n  Group sizes (how many rows share one hash):")
    for size, n_groups in sorted(template_ids_by_group.items()):
        print(f"    {size} rows: {n_groups} groups")

    print("\n  Sample duplicate groups (first 8):")
    for i, (h, rs) in enumerate(sorted(dup_groups.items(), key=lambda x: -len(x[1]))[:8]):
        r0 = rs[0]
        print(f"\n  --- Group {i+1}: {len(rs)} copies ---")
        print(f"  event: {r0.event!r}")
        print(f"  question: {r0.question!r}")
        print(f"  answer_options: {r0.answer_options!r}")

    question_counts = Counter((r.event, r.question) for r in valid)
    cross_template = Counter()
    item_by_key: dict[tuple[str, str, str], list] = defaultdict(list)
    for item, row in zip(items, rows):
        if row in validation.valid_rows:
            key = (row.event, row.question)
            item_by_key[key].append(item.template.id)

    for key, tpl_ids in item_by_key.items():
        if len(set(tpl_ids)) > 1 and len(tpl_ids) > 1:
            cross_template[len(set(tpl_ids))] += 1

    print("\n  Rows with identical event+question from multiple template ids:")
    multi = [(k, v) for k, v in item_by_key.items() if len(set(v)) > 1]
    print(f"    {len(multi)} event+question pairs produced by >1 template")
    for (event, question), tpl_ids in sorted(multi, key=lambda x: -len(x[1]))[:5]:
        print(f"    templates {sorted(set(tpl_ids))}: {event!r} | {question!r}")


if __name__ == "__main__":
    main()
