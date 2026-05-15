# Epic: Structured Content Generation System

**Client:** Serinn Labs  
**Contractor:** Foster Young LLC  
**Phase:** 1  
**Test Category:** MLB (Sports)  
**Target Delivery:** 5 weeks from inputs received  
**Plan status:** Office hours formalized (2026-04-13) — premises locked; alternatives and risks recorded below. **Implementation approach locked: B (2026-04-13).**

**Implementation tracking:** Rollup table and task checklists live under [Implementation progress](#implementation-progress) (update as epics ship).

---

## Overview

A locally-run Python application that transforms structured source input files (schedules, rosters, stat sheets) into fully populated, upload-ready CSV rows conforming to the client's schema. The system exposes a lightweight local web UI so the client or a team member can drop in files, configure parameters, and export a clean CSV — no terminal required after initial setup.

The architecture is modular: MLB sports is the first implemented category, but the system is designed so that new categories (markets, entertainment, news) can be added by dropping in a new input package and template config without touching core logic.

---

## Deliverable Summary

- Runnable Python application (local)
- Lightweight local web UI (browser-based, no deployment)
- Template and config system for question generation
- CSV export matching client upload schema
- Full documentation + setup guide
- Recorded walkthrough session

---

## Output Schema

Every generated row must conform to this structure:

| Field           | Format                                          |
| --------------- | ----------------------------------------------- |
| Category ID     | Provided via config (system-assigned on upload) |
| Subcategory     | String (e.g. "MLB")                             |
| Event           | String (e.g. "Mets vs Yankees")                 |
| Question        | String                                          |
| Answer Type     | "yes_no" or "multiple_choice"                   |
| Answer Options  | Pipe-delimited string (e.g. "Mets\|\|Yankees")  |
| Start Date      | ISO 8601 (e.g. 2026-05-14T19:10:00)             |
| Expiration Date | ISO 8601                                        |
| Resolution Date | ISO 8601                                        |
| Priority Flag   | "true" or "false"                               |

---

## System Architecture

```
INPUT FILES                CONFIG
(schedule, stats)    +   (templates, rules)
        |                       |
        └──────────┬────────────┘
                   ▼
          INPUT PARSER LAYER
     (normalizes + joins files)
                   |
                   ▼
       CONTROLLED GENERATION
        (LLM via OpenAI API)
                   |
                   ▼
         BATCH STRATEGY LAYER
      (50-200 rows per API call)
                   |
                   ▼
           LIGHT DEDUP + QA
      (remove dupes, schema checks)
                   |
                   ▼
          CSV EXPORT + UPLOAD
```

---

## Epic Breakdown

---

## Implementation progress

**Convention:** Keep the rollup table current as epics complete. For finished epics, task subsections use Markdown checklists (`[x]` / `[ ]`). Update this file when work ships so the doc stays the single source of truth for status.

| Epic | Topic | Status | Notes |
|------|-------|--------|-------|
| 1 | Project Setup and Environment | **Complete** | `requirements.txt`, `config/settings.yaml`, `main.py`, Flask UI (`ui/`), README setup, `.env.example`; `core/config.py` loads YAML + optional `settings.local.yaml` + `OPENAI_API_KEY` |
| 2 | Input Parser Layer | **In progress** | Multi-vertical inputs: `inputs.files` + `inputs.file_roles`; `load_normalized_bundle` + registry (`mlb`, `f1`); `NormalizedEvent.event_display`; profiles under `config/input_profiles/`; see README *Multi-vertical inputs* |
| 3 | Template and Config System | **Complete** | `templates/*.json` (6 MLB + 3 stubs); `core/template_config/` schema + loader; `templates_directory` in `config/settings.yaml`; `tests/test_templates.py` |
| 4 | Date Logic Layer | **Complete** | `core/date_rules.py` (engine); `config/settings.yaml` `date_rules` section (configurable offsets); `tests/test_date_rules.py` (6 passing tests); exported via `core/__init__.py` |
| 5 | Controlled Generation Layer | **In progress** | Tasks 5.1, 5.2, 5.3 complete |
| 6 | Deduplication and QA Layer | **In progress** | Task 6.1 complete |
| 7 | CSV Export | **Complete** | `core/csv_export.py` — `write_generated_csv`, `write_generated_csv_auto`, `build_generated_csv_path`, `sanitize_filename_component`, `DEFAULT_OUTPUT_DIR`; `tests/test_csv_export.py` |
| 8 | Local Web UI | Not started | |
| 9 | Documentation and Handoff | Not started | |

**Last updated:** 2026-04-28 (multi-vertical parser scaffolding + F1 normalizer)

### Adding a new vertical (checklist)

1. Register a `CategoryNormalizer` in `core/parsers/<vertical>/` and `@register_category_normalizer("<lowercase_key>")`.
2. Add `inputs.files.<Package>` slots and `inputs.file_roles.<Package>` unless using the MLB legacy `event_source` / `metric_source` pair.
3. Commit or generate `config/input_profiles/` YAML for detector mappings (`category_key` matches registry key; fingerprint may be `null` during bring-up).
4. Add templates under `templates/` with `subcategory` matching the UI package label.
5. Optionally set `topic_import_ids.<package>` and `inputs.packages.<vertical>` options (see `inputs.packages.f1`).

---

### EPIC 1 — Project Setup and Environment

**Goal:** Get the project running locally end to end before any logic is built.

**Status:** **Complete** (2026-04-14)

#### Task 1.1 — Repository and folder structure

- [x] Initialize project repo in Cursor
- [x] Define folder structure:
  ```
  /inputs          # user drops source files here
  /outputs         # generated CSVs land here
  /templates       # question template configs (JSON)
  /config          # global config file (YAML)
  /core            # generation, parsing, QA logic
  /ui              # Flask app and HTML front end
  main.py          # entry point
  requirements.txt
  README.md
  ```

#### Task 1.2 — Dependencies and requirements.txt

- [x] Python 3.10+ (required; documented in README)
- [x] `openai` — LLM API calls
- [x] `pandas` — input file parsing and CSV export
- [x] `openpyxl` — xlsx reading
- [x] `flask` — local web UI
- [x] `pyyaml` — config file parsing
- [x] `python-dateutil` — date arithmetic
- [x] `jinja2` — prompt templating

#### Task 1.3 — Python installation documentation

- [x] Write a setup section in README covering:
  - [x] How to check if Python is installed (`python --version`)
  - [x] Where to download Python 3.10+ (python.org)
  - [x] How to create a virtual environment (`python -m venv venv`)
  - [x] How to activate it (Mac/Linux vs Windows)
  - [x] How to install dependencies (`pip install -r requirements.txt`)
  - [x] How to add the OpenAI API key to environment or config

#### Task 1.4 — Global config file (config/settings.yaml)

- [x] Define all user-editable parameters in one place (committed `config/settings.yaml`; optional gitignored `config/settings.local.yaml`; `OPENAI_API_KEY` env override implemented in `core/config.py`):
  ```yaml
  openai_api_key: ""
  model: "gpt-5.4"
  topic_import_id: ""
  date_filter:
    start: "2026-05-15"
    end: "2026-06-01"
  batch_size: 100
  ```

---

### EPIC 2 — Input Parser Layer

**Goal:** Ingest any structured input file and normalize it into a standard internal format the generation layer can consume regardless of category.

#### Task 2.1 — Abstract input parser interface

- Define a base `InputParser` class with standard methods:
  - `load(filepath)` — reads the file
  - `normalize()` — returns a list of standardized event dicts
- All category-specific parsers inherit from this base

#### Task 2.2 — MLB schedule parser

- Reads `inputs/schedule.xlsx`
- Combines `event_date` and `Event_time` columns into a single datetime
- Applies date range filter from config
- Outputs normalized event records:
  ```json
  {
    "event_id": "MLB000657",
    "home_team": "Athletics",
    "away_team": "Giants",
    "event_datetime": "2026-05-15T21:40:00",
    "subcategory": "MLB"
  }
  ```

#### Task 2.3 — MLB player stats parser

- Reads `inputs/stats.xlsx`, uses 2026 sheet as source of truth for team assignment
- Filters out any rows where team is "2TM" (multi-team, ambiguous)
- Applies team name normalization map (full name → abbreviation):
  ```python
  TEAM_MAP = {
    "Mets": "NYM", "Yankees": "NYY", "Dodgers": "LAD",
    "Braves": "ATL", "Athletics": "ATH", "Giants": "SFG",
    # ... all 30 teams
  }
  ```
- Exposes a method `get_top_players(team, stat, n)` that returns top N players for a given team and stat column

#### Task 2.4 — Input validator

- On load, check that required columns are present
- Warn if date range yields zero rows
- Warn if any team in the schedule has no matching players in the stats file
- Surface errors clearly so the user knows what to fix before running

---

### EPIC 3 — Template and Config System

**Goal:** Define all question generation logic in config files, not in code, so new categories can be added without a code change.

**Status:** **Complete** (2026-04-14)

#### Task 3.1 — Template schema definition

- [x] Each template is a JSON file in `/templates`
- [x] Standard template fields:
  ```json
  {
    "id": "mlb_game_winner",
    "subcategory": "MLB",
    "question_family": "event",
    "question": "Who will win {home_team} vs {away_team}?",
    "answer_type": "multiple_choice",
    "answer_options": "{home_team}||{away_team}",
    "priority": 1,
    "requires_entities": false
  }
  ```
- [x] Entity-based templates include additional fields:
  ```json
  {
    "id": "mlb_home_run",
    "question_family": "entity_stat",
    "question": "Who will hit a home run?",
    "answer_type": "multiple_choice",
    "stat_column": "HR",
    "top_n_per_team": 2,
    "priority": "",
    "requires_entities": true
  }
  ```

#### Task 3.2 — MLB Phase 1 templates (game-level)

- [x] Template: Game Winner (`mlb_game_winner.json`)
- [x] Template: Win by more than 2 runs (yes/no) (`mlb_win_margin_2.json`)
- [x] Template: Total runs exceed 8.5 (yes/no) (`mlb_total_runs_over_8_5.json`)

#### Task 3.3 — MLB Phase 1 templates (player/stat-level)

- [x] Template: Who will hit a home run? (HR, top 2 per team) (`mlb_home_run.json`)
- [x] Template: Which player will record an RBI? (RBI, top 2 per team) (`mlb_rbi.json`)
- [x] Template: Who is more likely to steal a base? (SB, top 2 per team) (`mlb_steal_base.json`)

#### Task 3.4 — Stub templates for future categories

- [x] Create placeholder template files for markets, news, entertainment (`*_placeholder.json`)
- [x] Same schema, placeholder values
- [x] Comment in each (`_comment`): "extend by adding question and input package definition"

---

### EPIC 4 — Date Logic Layer

**Goal:** Deterministically compute all three date fields from event datetime and config rules.

**Status:** **Complete** (2026-04-14)

#### Task 4.1 — Date rule engine

- [x] Implement as a standalone function, not baked into generation
- [x] Rules (per client spec):
  - [x] `start_date` = event_datetime - 24 hours
  - [x] `expiration_date` = event_datetime
  - [x] `resolution_date` = event_datetime + 4 hours
- [x] Output format: ISO 8601 without timezone offset (per client example)
- [x] Make lead/lag values configurable in settings.yaml so they can be changed per category without code changes

**Leave-behind notes (Task 4.1):**

| What | File | Details |
|------|------|---------|
| Date rule engine | `core/date_rules.py` | Standalone module. `compute_question_dates(event_datetime, category_key, settings)` returns a `QuestionDates` dataclass with `start_date`, `expiration_date`, `resolution_date` as naive ISO 8601 strings. `parse_event_datetime()` handles string and `datetime` inputs, strips timezone info. `get_date_rules_for_category()` merges `date_rules.default` with per-category overrides from settings. |
| Configurable offsets | `config/settings.yaml` | `date_rules.default` and `date_rules.mlb` sections define `start_offset_hours`, `expiration_offset_hours`, `resolution_offset_hours`. New categories can be added as sibling keys (e.g. `date_rules.markets`) without code changes. Unknown categories fall back to `default`. |
| Package exports | `core/__init__.py` | `compute_question_dates` and `QuestionDates` exported for use by downstream epics (generation, row assembly). |
| Tests | `tests/test_date_rules.py` | 6 tests: default MLB offsets, category override, unknown category fallback, no timezone suffix in output, `datetime` input acceptance, merge behavior. All passing. |

---

### EPIC 5 — Controlled Generation Layer

**Goal:** Use the OpenAI API to generate clean, well-worded question text within the structure defined by templates. The LLM handles natural language quality — phrasing, player name handling, grammatical cleanup — but does not invent question structures. All question types, answer formats, and priority rules are defined by templates and config.

**Status:** **Complete** (2026-04-14)

**Confirmed approach (Phase 1):** Template-driven (Option A). The LLM is used within templates, not instead of them. Architecture should leave a hook for a future dynamic generation mode without requiring a rewrite.

#### Task 5.1 — Prompt builder

**Status:** **Complete** (2026-04-14)

- [x] Takes a template + normalized event record and builds a structured prompt
- [x] For event-level questions: slots in home_team, away_team, event values and instructs the LLM to produce clean, natural-sounding question text matching the template structure
- [x] For entity questions: includes the resolved player list in the prompt context and instructs the LLM to construct answer options and wording cleanly
- [x] System prompt enforces:
  - [x] Output format: JSON object with `"questions"` array, one per input item
  - [x] Do not invent new question types — only produce output conforming to the supplied template
  - [x] Answer options must exactly match the entities provided — no hallucinated player names
- [x] Include a `generation_mode` field in the prompt config (set to `"template"` for Phase 1) so a future `"dynamic"` mode can be added without restructuring the prompt builder
- [x] Pydantic response schemas (`GeneratedQuestion`, `GeneratedQuestionBatch`) defined for OpenAI structured-output parsing (per eng review amendment)
- [x] Batch-aware: `build_prompt()` accepts a list of `PromptItem` objects so Task 5.2 can chunk work freely
- [x] Tests: 35 passing (config, placeholder fill, event prompts, entity prompts, batch prompts, system-prompt contract, Pydantic schemas)

**Leave-behind notes (Task 5.1):**

| What | File | Details |
|------|------|---------|
| Generation package | `core/generation/__init__.py` | New package. Exports `PromptBuilder`, `PromptConfig`, `PromptItem`, `GeneratedQuestion`, `GeneratedQuestionBatch`. |
| Prompt builder | `core/generation/prompt_builder.py` | `PromptBuilder` class with `build_prompt(items)` and `build_single_prompt(item)`. Assembles system + user messages for OpenAI chat API. `PromptConfig(generation_mode="template")` — frozen dataclass; future `"dynamic"` mode requires no structural change. `fill_template_placeholders()` and `fill_event_answer_options()` are exposed as standalone helpers. |
| Response schemas | `core/generation/prompt_builder.py` | `GeneratedQuestion` and `GeneratedQuestionBatch` Pydantic models. `GeneratedQuestionBatch` wraps `{"questions": [...]}` — designed for `response_format` / `chat.completions.parse` in Task 5.2. `PromptBuilder.response_schema` property returns the batch model class. |
| Core exports | `core/__init__.py` | Updated to re-export all generation symbols (`PromptBuilder`, `PromptConfig`, `PromptItem`, `GeneratedQuestion`, `GeneratedQuestionBatch`). |
| Tests | `tests/test_prompt_builder.py` | 35 tests across 9 classes: `TestPromptConfig` (defaults, freeze), `TestFillTemplatePlaceholders` (home/away, line), `TestFillEventAnswerOptions` (team options, yes/no), `TestPromptBuilderStructure` (message shape, mode, schema, validation), `TestEventPrompt` (data presence, filled question, options, line), `TestEntityPrompt` (player names, stat column, missing-players error, ONLY directive), `TestBatchPrompt` (numbering, count, mixed types), `TestSystemPromptContract` (JSON format, no-invent, no-hallucinate, exact-match), `TestResponseSchemas` (round-trip, JSON parse, schema shape). |

#### Task 5.2 — Batch execution

**Status:** **Complete** (2026-04-14)

- [x] Groups events into batches of N (configurable, default 100)
- [x] Sends one API call per batch
- [x] Parses JSON response back into row dicts
- [x] Handles API errors gracefully — logs failed batches, continues processing, reports at end

**Leave-behind notes (Task 5.2):**

| What | File | Details |
|------|------|---------|
| Batch executor | `core/generation/batch_executor.py` | New module. `BatchExecutor` class accepts `settings` dict, optional `PromptBuilder`, and optional `OpenAI` client. `execute(items)` chunks `PromptItem` list by `batch_size` (from settings, default 100), calls `client.beta.chat.completions.parse()` per chunk with `GeneratedQuestionBatch` as `response_format`, and aggregates results. Failed batches are logged and skipped — never abort the run. Returns `BatchResult` dataclass with `.questions`, `.failed_batches`, `.total_batches`, `.successful_batches`, `.all_succeeded`, `.total_questions`. |
| Result types | `core/generation/batch_executor.py` | `BatchResult` (aggregated output + failure metadata) and `FailedBatch` (batch index, item count, error message) dataclasses. |
| Package exports | `core/generation/__init__.py` | Updated — now exports `BatchExecutor`, `BatchResult`, `FailedBatch` alongside existing Task 5.1 symbols. |
| Core exports | `core/__init__.py` | Updated — re-exports `BatchExecutor`, `BatchResult`, `FailedBatch` for use by downstream epics. |
| Configurable batch size | `config/settings.yaml` | `batch_size: 100` already present; `BatchExecutor` reads it at init. Override per-run via settings or constructor. |
| Tests | `tests/test_batch_executor.py` | 32 tests across 8 classes: `TestBatchResult` (defaults, flags), `TestChunking` (even split, remainder, empty, coercion), `TestClientInit` (missing key, injection, model fallback), `TestExecuteHappyPath` (empty input, single batch, multi-batch aggregation, model/format/messages forwarding), `TestExecuteErrorHandling` (partial failure continues, all-fail, item counts, refusal detection, null-parsed), `TestPromptBuilderInjection` (default vs custom), `TestDefaults` (constant, fallback), `TestLogging` (no-crash smoke). All passing. |

#### Task 5.3 — Output row assembly

**Status:** **Complete** (2026-04-14)

- [x] For each generated question, assembles the full output row:
  - [x] Pulls Topic Import ID from config
  - [x] Pulls subcategory from template
  - [x] Constructs event string from event record
  - [x] Inserts LLM-generated question text
  - [x] Inserts answer type and options (from template or entity resolution)
  - [x] Computes date fields via date rule engine
  - [x] Sets priority flag from template
- [x] `OutputRow` dataclass with `to_dict()` returning columns in client schema order
- [x] `OUTPUT_COLUMNS` constant defining the 10-column client upload schema
- [x] `RowAssembler.assemble()` for single-row assembly, `assemble_batch()` for lists with positional or key-based matching
- [x] `build_event_string()` helper constructs `"{away_team} vs {home_team}"`
- [x] Tests: 35 passing across 8 classes

**Leave-behind notes (Task 5.3):**

| What | File | Details |
|------|------|---------|
| Row assembler module | `core/generation/row_assembler.py` | New module. `RowAssembler` class accepts `settings` dict at init, reads Topic Import ID. `assemble(generated, item)` combines a `GeneratedQuestion` + `PromptItem` into an `OutputRow` — pulls Topic Import ID from settings, `subcategory` and `priority` from template, event string from `build_event_string()`, question text and answer_options from the LLM result, `answer_type` from template, dates via `compute_question_dates()`. `assemble_batch()` handles list matching (positional when order matches, key-based `(template_id, event_id)` fallback when LLM reorders). Unmatched questions logged and skipped. |
| Output row type | `core/generation/row_assembler.py` | `OutputRow` frozen dataclass with 10 fields matching client schema. `to_dict()` returns an ordered dict keyed by `OUTPUT_COLUMNS`. `OUTPUT_COLUMNS` constant defines column names and order: `topic_import_id`, `subcategory`, `event`, `question`, `answer_type`, `answer_options`, `start_date`, `expiration_date`, `resolution_date`, `priority`. |
| Event string helper | `core/generation/row_assembler.py` | `build_event_string(event)` → `"{away_team} vs {home_team}"`. Standalone function, reusable by downstream CSV/QA. |
| Package exports | `core/generation/__init__.py` | Updated — now exports `RowAssembler`, `OutputRow`, `OUTPUT_COLUMNS`, `build_event_string` alongside existing Task 5.1 and 5.2 symbols. |
| Core exports | `core/__init__.py` | Updated — re-exports `RowAssembler`, `OutputRow`, `OUTPUT_COLUMNS`, `build_event_string` for use by downstream epics (CSV writer, QA layer). |
| Tests | `tests/test_row_assembler.py` | 35 tests across 8 classes: `TestBuildEventString` (standard, different teams), `TestOutputRow` (column order, values), `TestOutputColumns` (count, names), `TestRowAssemblerSingle` (Topic Import ID from settings/missing, subcategory, event string, question from LLM, answer_type multiple_choice/yes_no, answer_options event/entity, numeric/blank priority), `TestDateComputation` (start −24h, expiration =event, resolution +4h, direct engine match, different datetime, subcategory→category_key), `TestAssembleBatch` (empty, positional single/multi, key-based reorder, key mismatch skip, mixed templates), `TestRowAssemblerInit` (Topic Import ID, missing defaults, settings stored), `TestEndToEndRow` (full event/yesno/entity row round-trip). All passing. |

#### Task 5.4 — Token cost logging

**Status:** **Complete** (2026-04-14)

- [x] After each run, log approximate token usage and estimated cost to console
- [x] Keeps the client informed without surprises on the API bill
- [x] `TokenUsage` dataclass captures prompt, completion, and total tokens per API call
- [x] `RunCostSummary` aggregates across all batches with estimated USD cost
- [x] Pricing is configurable via `model_pricing` in `settings.yaml` — no code changes needed when rates change or new models are added
- [x] Built-in defaults for `gpt-4o`, `gpt-4o-mini`, `gpt-5.4`; unknown models fall back to conservative rates
- [x] `BatchExecutor` extracts `response.usage` from every successful API call, attaches `token_usages` and `cost_summary` to `BatchResult`
- [x] End-of-run report logs human-readable token counts (comma-formatted) and estimated cost in USD
- [x] Existing `test_batch_executor.py` mock updated to include `usage` fields (32 tests still passing)
- [x] Tests: 38 passing (5 new test classes + 1 integration class)

**Leave-behind notes (Task 5.4):**

| What | File | Details |
|------|------|---------|
| Token tracker module | `core/generation/token_tracker.py` | New module. `TokenUsage` dataclass (prompt/completion/total tokens). `RunCostSummary` dataclass (aggregated tokens, estimated USD cost, model, per-batch usages). `extract_token_usage(response)` safely pulls token counts from an OpenAI API response (handles `None`/missing `.usage`). `estimate_cost()` computes USD from token counts × per-model pricing. `build_cost_summary()` aggregates a list of `TokenUsage` into a `RunCostSummary`. `log_cost_summary()` logs formatted token counts and estimated cost via the `generation` logger. |
| Configurable pricing | `config/settings.yaml` | New `model_pricing` section with per-model `input`/`output` rates (USD per 1M tokens). Entries for `gpt-4o`, `gpt-4o-mini`, `gpt-5.4`. Add new models as sibling keys — unknown models fall back to built-in conservative defaults ($5/1M input, $15/1M output). Settings override takes precedence over hardcoded defaults. |
| Batch executor changes | `core/generation/batch_executor.py` | `_execute_batch()` now returns `(questions, TokenUsage)` tuple. `execute()` accumulates `token_usages` list on `BatchResult`, builds `cost_summary` via `build_cost_summary()` after all batches complete. `_report()` calls `log_cost_summary()` when summary is present. `BatchResult` dataclass extended with `token_usages: list[TokenUsage]` and `cost_summary: RunCostSummary | None` fields. |
| Existing test fix | `tests/test_batch_executor.py` | `_mock_openai_response()` updated to include `.usage` with `prompt_tokens=100`, `completion_tokens=50`, `total_tokens=150` so token extraction doesn't encounter MagicMock objects. All 32 existing tests still passing. |
| Package exports | `core/generation/__init__.py`, `core/__init__.py` | Updated — now export `TokenUsage`, `RunCostSummary`, `extract_token_usage`, `estimate_cost`, `build_cost_summary`, `log_cost_summary` alongside existing EPIC 5 symbols. |
| Tests | `tests/test_token_tracker.py` | 38 tests across 9 classes: `TestTokenUsage` (defaults, explicit), `TestRunCostSummary` (defaults, batch_count, model), `TestExtractTokenUsage` (real response, None usage, missing attr, partial fields, None coercion), `TestResolvePricing` (builtin, fallback, settings override, unknown override, empty/None pricing), `TestEstimateCost` (zero, known model, proportional, unknown fallback, settings override, None settings, precision), `TestBuildCostSummary` (empty, single, multi-aggregate, cost match, settings passthrough, preserves usages), `TestLogCostSummary` (no-error, token counts in log, cost/model in log, zero-cost), `TestBatchExecutorTokenIntegration` (usages captured, summary present, multi-batch aggregate, failed-batch excluded, empty-input zero-cost). All passing. |

---

### EPIC 6 — Deduplication and QA Layer

**Goal:** Catch bad output before it hits the CSV.

**Status:** **Complete** (2026-04-14)

#### Task 6.1 — Deduplication

**Status:** **Complete** (2026-04-14)

- [x] Hash each row on (subcategory + event + question)
- [x] Remove exact duplicates
- [x] Flag near-duplicates (same event, similar question text) for review — write to a separate `flagged.csv` rather than silently dropping

**Leave-behind notes (Task 6.1):**

| What | File | Details |
|------|------|---------|
| Deduplication module | `core/dedup.py` | New module. `row_hash(row)` computes SHA-256 from `(subcategory, event, question)` for exact-duplicate detection. `deduplicate(rows, *, similarity_threshold=0.85)` runs a two-pass pipeline: (1) exact dedup via hash, keeping first occurrence; (2) near-duplicate flagging via `difflib.SequenceMatcher` on question text for rows sharing the same event. Returns `DeduplicationResult` dataclass with `clean_rows`, `flagged_rows`, `flagged_pairs`, `exact_duplicates_removed`, `near_duplicates_flagged`, and `total_input` property. No new dependencies — uses only stdlib (`hashlib`, `difflib`, `csv`). |
| Near-duplicate detection | `core/dedup.py` | `_find_near_duplicates(rows, threshold)` groups rows by event, compares question text pairwise within each event using case-insensitive `SequenceMatcher.ratio()`. Both rows in a similar pair are flagged. `NearDuplicatePair` dataclass records `row_a`, `row_b`, `similarity`, and human-readable `reason`. `DEFAULT_SIMILARITY_THRESHOLD = 0.85` — configurable per call. |
| Flagged CSV writer | `core/dedup.py` | `write_flagged_csv(flagged_rows, pairs, output_path)` writes flagged rows to CSV with the standard 10 output columns plus `similarity` and `reason` columns for reviewer context. Auto-creates parent directories. Default path: `outputs/flagged.csv`. |
| Package exports | `core/__init__.py` | Updated — now exports `deduplicate`, `DeduplicationResult`, `NearDuplicatePair`, `DEFAULT_SIMILARITY_THRESHOLD`, `row_hash`, `write_flagged_csv` alongside existing symbols. |
| Tests | `tests/test_dedup.py` | 41 tests across 8 classes: `TestRowHash` (deterministic, key-field-only, hex format, SHA-256 length), `TestQuestionSimilarity` (identical, case-insensitive, different, similar), `TestRemoveExactDuplicates` (no dupes, exact dupe, three copies, empty, order preservation, non-key field difference), `TestFindNearDuplicates` (no near-dupes, flagged, different events not compared, threshold boundary, similarity recording, multiple near-dupes), `TestDeduplicate` (empty, no duplicates, exact only, near only, exact-then-near ordering, total_input, custom threshold, clean excludes flagged), `TestDeduplicationResult` (defaults, total_input), `TestWriteFlaggedCsv` (file creation, columns, row count, similarity/reason content, empty input, nested directories), `TestDefaultThreshold` (value, range). All passing. |

#### Task 6.2 — Schema validation

**Status:** **Complete** (2026-04-14)

- [x] Check every row has all required fields populated
- [x] Validate answer_type is exactly "yes_no" or "multiple_choice"
- [x] Validate date fields parse as valid ISO 8601
- [x] Validate priority is a non-negative integer or blank
- [x] Any row failing validation is written to `outputs/errors.csv` with a reason column

**Leave-behind notes (Task 6.2):**

| What | File | Details |
|------|------|---------|
| Schema validation module | `core/schema_validator.py` | New module. `validate_row(row)` checks a single `OutputRow` and returns a list of failure reasons (empty = valid). `validate_rows(rows)` runs validation on all rows and returns a `ValidationResult` dataclass partitioning rows into `valid_rows` and `invalid_rows` (each carrying its failure `reasons`). Validates four rules: (1) required output columns must be non-empty, while `priority` may be blank; (2) `answer_type` must be exactly `"yes_no"` or `"multiple_choice"` (case-sensitive); (3) `start_date`, `expiration_date`, `resolution_date` must parse as valid ISO 8601 (supports `YYYY-MM-DDTHH:MM:SS`, `YYYY-MM-DD`, and timezone-aware formats); (4) `priority` must be a non-negative integer or blank. No new dependencies — uses only stdlib (`csv`, `datetime`, `pathlib`, `logging`). |
| Error CSV writer | `core/schema_validator.py` | `write_errors_csv(errors, output_path)` writes invalid rows to CSV with the standard 10 output columns plus a `reason` column. Multiple failures on the same row are semicolon-separated. Auto-creates parent directories. Default path: `outputs/errors.csv`. |
| Dataclasses | `core/schema_validator.py` | `RowValidationError` holds a reference to the failing `OutputRow` and its `reasons: list[str]`. `ValidationResult` holds `valid_rows`, `invalid_rows`, and computed properties `total_input`, `valid_count`, `invalid_count`. |
| Package exports | `core/__init__.py` | Updated — now exports `validate_row`, `validate_rows`, `ValidationResult`, `RowValidationError`, `write_errors_csv`, `REQUIRED_FIELDS`, `VALID_ANSWER_TYPES`, `DATE_FIELDS` alongside existing EPIC 5 and 6.1 symbols. |
| Tests | `tests/test_schema_validator.py` | 49 tests across 7 classes: `TestIsValidIso8601` (datetime no-tz, date-only, tz-aware, garbage, empty, partial, leap day valid/invalid), `TestValidateRow` (valid row, missing-field variants, whitespace-only, invalid/valid answer_type, invalid dates, valid dates, invalid/valid priority, multiple failures, case sensitivity), `TestValidateRows` (all valid, all invalid, mixed, empty input, total_input, reasons present, identity preservation), `TestValidationResult` (defaults, properties), `TestWriteErrorsCsv` (file creation, columns, row count, reason content, empty input, nested dirs, data match, single-reason no semicolon), `TestConstants` (required fields, answer types, date fields). All 49 passing. |

#### Task 6.3 — QA summary report

**Status:** **Complete** (2026-04-14)

- [x] After each run, print a summary to console:
  - [x] Total rows generated
  - [x] Rows passed validation
  - [x] Rows flagged as near-duplicate
  - [x] Rows written to errors
  - [x] Estimated API cost

**Leave-behind notes (Task 6.3):**

| What | File | Details |
|------|------|---------|
| QA summary module | `core/qa_summary.py` | New module. `QASummary` dataclass holds aggregated run stats: `total_rows_generated`, `rows_passed_validation`, `rows_failed_validation`, `rows_flagged_near_duplicate`, `exact_duplicates_removed`, `estimated_cost_usd` (nullable). `has_cost` property distinguishes available vs unavailable cost data. |
| Builder function | `core/qa_summary.py` | `build_qa_summary(validation, dedup, cost=None)` accepts `ValidationResult`, `DeduplicationResult`, and optional `RunCostSummary` — the three result objects already produced by the pipeline — and returns a `QASummary`. No new dependencies. |
| Formatter function | `core/qa_summary.py` | `format_qa_summary(summary)` returns a multi-line, human-readable string with separator bars, all five required metrics (total rows, passed validation, written to errors, flagged as near-duplicate, estimated API cost), plus exact-duplicates-removed as a bonus line. Cost displays as `$X.XXXX USD` when present, `N/A` otherwise. |
| Console printer | `core/qa_summary.py` | `print_qa_summary(validation, dedup, cost=None, *, file=None)` is the main entry point — builds, formats, and prints the report to `sys.stdout` (or a custom `TextIO`). Also emits a structured `INFO` log via `logging`. Returns the `QASummary` for programmatic access. |
| Package exports | `core/__init__.py` | Updated — now exports `QASummary`, `build_qa_summary`, `format_qa_summary`, `print_qa_summary` alongside existing EPIC 5, 6.1, and 6.2 symbols. |
| Tests | `tests/test_qa_summary.py` | 35 tests across 5 classes: `TestQASummary` (has_cost true/false/zero, field access), `TestBuildQaSummary` (all valid, mixed, with/without cost, empty run, all invalid), `TestFormatQaSummary` (separators, header, all five metric values, labels, cost/N/A/zero-cost, multiline), `TestPrintQaSummary` (custom file, return value, cost object, N/A, logging, log counts, empty run, stdout default), `TestIntegration` (full pipeline round-trip, large numbers). All 35 passing. |

---

### EPIC 7 — CSV Export

**Goal:** Write a clean, upload-ready CSV with correct column names and formatting.

**Status:** **Complete** (2026-04-17)

#### Task 7.1 — CSV writer

**Status:** **Complete** (2026-04-17)

- [x] Column order matches client schema exactly
- [x] No index column
- [x] UTF-8 encoding
- [x] Output filename: `outputs/generated_{subcategory}_{date_window}_{timestamp}.csv`

#### Task 7.2 — Output directory management

**Status:** **Complete** (2026-04-17)

- [x] Auto-create `/outputs` if it doesn't exist
- [x] Never overwrite a previous output — always timestamp the filename

**Leave-behind notes (EPIC 7):**

| What | File | Details |
|------|------|---------|
| Main CSV export | `core/csv_export.py` | `write_generated_csv(rows, path)` writes UTF-8 CSV via `csv.DictWriter` with `OUTPUT_COLUMNS` only (no index column). `build_generated_csv_path(subcategory, date_window_start, date_window_end, …)` builds `generated_{sanitized_subcategory}_{start}_to_{end}_{timestamp}.csv` under project `outputs/` by default; timestamp uses `%Y%m%d_%H%M%S_%f` (microseconds) so successive runs never collide. `write_generated_csv_auto(rows, subcategory=…, date_filter=…)` combines path build + write. `sanitize_filename_component()` restricts subcategory to safe path segments. |
| Default output dir | `core/csv_export.py` | `DEFAULT_OUTPUT_DIR` = repo `outputs/` resolved from `Path(__file__)`, not process cwd. |
| Package exports | `core/__init__.py` | Exports `DEFAULT_OUTPUT_DIR`, `build_generated_csv_path`, `sanitize_filename_component`, `write_generated_csv`, `write_generated_csv_auto`. |
| Tests | `tests/test_csv_export.py` | 17 tests: sanitize, path pattern, date slash normalization, unique paths, column order, UTF-8, nested mkdir, empty rows header-only, auto writer, default dir. |

---

### EPIC 8 — Local Web UI

**Goal:** Wrap the script in a minimal browser-based interface so the client can run it without using the terminal after initial setup.

#### Task 8.1 — Flask app skeleton

- Single-page app served at `localhost:5000`
- Routes:
  - `GET /` — main UI
  - `POST /run` — triggers generation run
  - `GET /download/<filename>` — serves output CSV

#### Task 8.2 — UI: file upload

- Two file drop zones: Schedule and Stats
- Accepts .xlsx files
- Files saved to `/inputs` on upload

#### Task 8.3 — UI: config panel

- Editable fields rendered from settings.yaml:
  - Date range (start / end)
  - Category / subcategory
  - Top N per team (for entity questions)
  - Template toggles (checkboxes to enable/disable each template)
- Changes written back to settings.yaml on run

#### Task 8.4 — UI: run and output

- "Generate" button triggers the pipeline
- Progress indicator while running
- On completion: summary stats displayed (rows generated, errors, cost estimate)
- Download button for the output CSV
- Download button for errors.csv if any errors exist

#### Task 8.5 — UI: basic styling

- Clean, minimal, functional
- No external dependencies — plain HTML/CSS only
- Should work in any modern browser

---

### EPIC 9 — Documentation and Handoff

**Goal:** Client or intern can set up and run the system independently without help.

#### Task 9.1 — README.md

- What the system does (one paragraph)
- Prerequisites: Python 3.10+, OpenAI API key
- Python installation instructions (Mac, Windows)
- Setup steps (clone/download, venv, pip install)
- How to add API key
- How to start the app (`python main.py`)
- How to use the UI
- How to add a new category (pointer to templates folder)
- Troubleshooting section (common errors and fixes)

#### Task 9.2 — Template authoring guide

- How to write a new template JSON
- Field definitions and valid values
- Event-level vs entity-stat template differences
- Example: adding a new sports subcategory
- Example: adding a markets category

#### Task 9.3 — Recorded walkthrough

- Screen recording covering:
  - Initial setup from scratch
  - Loading the MLB files
  - Running a generation job
  - Reviewing output and errors
  - How to adjust config and re-run

---

## Out of Scope (Phase 1)

- Live deployed service
- Real-time data fetching
- Deep third-party API integrations beyond OpenAI
- Production infrastructure
- Automated scheduling or cron-based runs
- User authentication

---

## Definition of Done

Phase 1 is complete when:

- The system accepts the MLB schedule and stats files as inputs
- Runs end to end and produces a valid CSV matching the client schema
- All three game-level templates and all three player-stat templates generate correct output
- Date fields are correctly computed for all rows
- QA layer catches and reports schema errors
- UI allows file upload, config edit, run, and CSV download without terminal
- README allows a non-technical user to set up and run the system from scratch
- Recorded walkthrough is delivered

---

## Office Hours — Plan Formalization (GStack)

*Session mode: contract delivery (client + fixed scope). The Epic already contained a complete execution plan; interactive YC-style demand discovery was skipped in favor of premise check, alternatives, and risk pass.*

### Context

- **Branch / repo:** `main` in workspace; application code not yet present — this document is the source of truth for scope.
- **Framing:** Serinn Labs needs a **local** pipeline from spreadsheets → validated CSV rows matching their upload schema, with **templates in config** so MLB is first category, not the only architecture.

### Landscape (Search Before Building)

| Layer | Takeaway |
| ----- | -------- |
| **1 — Tried and true** | Separate ingestion from generation; batch work in chunks; validate every row against a schema; never trust raw LLM text for IDs/dates/options without deterministic assembly. |
| **2 — Current discourse** | Batch LLM→CSV pipelines fail on timeouts, rate limits, JSON/CSV quoting drift, and schema rejection when “structured output” is pushed too far in one call. Chunking (e.g. 25–500 rows per request), bounded retries, and per-row status metadata are standard mitigations. |
| **3 — First principles for this Epic** | Your design already **limits the LLM to wording** inside fixed templates; **dates and options are deterministic** from code + data. That division of labor is the right move for cost, auditability, and upload safety. **EUREKA (for this plan):** “Everyone lets the model invent rows” is the common failure mode; your Epic explicitly does not — keep that invariant in implementation. |

### Premises (agree before build)

1. **Contract truth** — Delivery is defined by **Definition of Done** + client schema; “nice to have” does not ship in Phase 1 unless change order. **Agree** (implicit in Epic).
2. **Trust boundary** — The LLM may polish **question strings** only; **answer options for player templates** must come from **resolved stats** (no invented players). **Agree** (matches EPIC 5 Task 5.1).
3. **Category growth** — New markets/verticals ship by **new parsers + templates**, not forks of core logic. **Agree** (Overview + EPIC 2/3).
4. **No deployment** — Local Flask + file drop is sufficient; auth and hosted infra stay out of scope. **Agree** (Out of Scope).

### Approaches considered

| | **Approach A — Minimal viable (ship fastest)** | **Approach B — Ideal architecture (Epic as written)** | **Approach C — Lateral (max determinism)** |
| -- | ---------------------------------------------- | ----------------------------------------------------- | ------------------------------------------ |
| **Summary** | Thin CLI: parsers + Jinja prompts + single CSV out; Flask later. | Full vertical slice: parsers, templates, dates, batch gen, QA, UI, docs — per Epic order. | Deterministic row bodies (code fills question text from templates); LLM optional or for copy-only variants; strongest anti-hallucination. |
| **Effort** | S | M–L (5-week box) | M |
| **Risk** | Med — UI and handoff deferred; client may need UI sooner. | Low–Med — scope is clear; watch API cost and batch failures. | Med — may over-fit; client asked for LLM “quality” on language. |
| **Pros** | Fastest path to “CSV in hand.” | Matches contract; one coherent handoff. | Lowest trust risk on options/entities. |
| **Cons** | Does not match “no terminal after setup” alone. | More moving parts to integrate. | May duplicate product intent if naturalness suffers. |

**RECOMMENDATION:** **Approach B (build the Epic as specified)** — it matches the signed scope, delivers the local UI and documentation the client needs, and already encodes the right LLM boundary. Use Approach A only if the schedule slips and you need a **milestone CSV** before UI polish; use Approach C selectively for **entity rows** if QA shows residual name/option drift.

### Decision — locked (office hours)

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| **Phase 1 implementation approach** | **B — Full Epic (ideal architecture)** | Matches **Definition of Done** in one delivery: local UI (no terminal after setup), six MLB templates, QA, CSV, README, walkthrough. A and C remain **contingencies** only (schedule slip → milestone CSV; QA drift on entities → tighten determinism inside Approach B — not a fork). |

**Implications:**

- Build **one** pipeline invoked from both CLI (optional/dev) and **Flask `/run`** — avoid maintaining separate generation paths.
- **EPIC 8** is in scope for Phase 1, not a follow-on phase.
- If timeline pressure appears mid-project, **shrink date window / template toggles** in config first; only then consider a time-boxed CSV-only milestone (A-style) without redefining the locked approach.

### Critical path (suggested sequencing)

1. **EPIC 1** — runnable skeleton + `settings.yaml` (prove `main.py` + venv story).
2. **EPIC 2 + 4** — normalized events + date engine (no API cost; testable unit outputs).
3. **EPIC 3** — templates locked for six MLB Phase 1 templates.
4. **EPIC 5 → 6 → 7** — generation + QA + CSV (core value).
5. **EPIC 8** — Flask wrapper on the same pipeline (avoid two divergent “run” paths).
6. **EPIC 9** — README, template guide, recording last (reflect final behavior).

### Risks & mitigations

| Risk | Mitigation |
| ---- | ---------- |
| JSON parse failures / truncated batches | Log batch id; retry with smaller `batch_size`; write partial successes; never silent drop. |
| Hallucinated or extra player names | Validator rejects options not in resolved list; errors → `errors.csv`. |
| Near-duplicate definition too loose/tight | Define similarity threshold in code + document behavior; keep `flagged.csv` human-reviewable. |
| API cost surprises | Token/cost logging (EPIC 5.4) + dry-run with tiny date window in config. |
| Client schema drift | Single module mapping internal row → column order; assert columns on write. |

### Open questions (resolve with client if ambiguous)

- **Category ID:** Epic says system-assigned on upload — confirm whether CSV may leave blank or must use placeholder.
- **Timezone:** Schedule + stats combine to naive ISO — confirm all events are single-timezone or document assumption (e.g. venue local).
- **“Near duplicate”** — confirm whether fuzzy match is required in Phase 1 or exact dedupe + manual flagging is enough.

### The assignment (next concrete action)

**Initialize the application repo inside this workspace** (or a dedicated repo): create the folder layout in EPIC 1 Task 1.1, add `requirements.txt`, a no-op `main.py` that loads config, and a one-page README with venv steps — so the next session is **parser work**, not scaffolding debate.

### Delivery signals observed in this plan

- **Specific schema and file shapes** (schedule columns, stats sheet, TEAM_MAP) — executable, not vague.
- **Clear LLM boundary** (templates + “do not invent types”) — reduces downstream trust bugs.
- **Explicit out-of-scope** — avoids scope creep into hosting and cron.

---

## Plan: Engineering Review (/plan-eng-review)

**Design doc:** `~/.gstack/projects/serinn-labs-question-generator/jackcarlson-main-design-20260413-150729.md`  
**Test plan:** `~/.gstack/projects/serinn-labs-question-generator/jackcarlson-main-eng-review-test-plan-20260413-151157.md`  
**Branch:** `main` (workspace; application code greenfield)

### Step 0 — Scope challenge

| Check | Result |
| ----- | ------ |
| **Existing code** | None yet — no parallel flows to retire. |
| **Minimum viable scope** | Already narrowed to MLB + six templates + local UI; defer multi-category parsers beyond stubs. |
| **Complexity / file smell** | Many modules, but **incremental PRs** (parsers → dates → gen → QA → CSV → UI) keep each change set small — **no single PR should touch 8+ files** without necessity. |
| **Search / built-ins** | **[Layer 2]** OpenAI **Structured Outputs** / `parse()` + Pydantic reduces JSON breakage vs prompt-only arrays — **add explicitly to EPIC 5** (not an “ocean”; one SDK feature). **[Layer 2]** Long Flask requests → **background work + polling** is standard for local tools; Celery is **out of scope**. |
| **TODOS.md** | Created in repo root from this review (`TODOS.md`). |
| **Completeness** | Plan already aims for full QA + UI + docs — **boil the lake** on tests for parsers, dates, validation, and job/download paths. |

### Decision locked (you chose)

| Topic | Decision | Notes |
| ----- | -------- | ----- |
| **Flask long-running generation** | **B — Background job + job id + polling** | `POST /run` returns quickly with `job_id`; UI polls e.g. `GET /run/status/<job_id>` for phase, counts, errors; avoids browser/proxy timeouts on multi-minute OpenAI batches. Implementation: **in-process thread + locked job dict** is enough for single-user local; no Celery. |

### Plan amendments (apply during implementation)

1. **EPIC 5 — Structured outputs:** Prefer `response_format` / `chat.completions.parse` with a Pydantic model for “batch of rows” so validation is **machine-checked**, not regex-repaired. Keep template-driven semantics; schema encodes **allowed fields**, not business rules (those stay in code).
2. **EPIC 8 — Routes:** Extend Task 8.1 to include **`GET /run/status/<job_id>`** (and optionally `POST /run` only starts the job; separate `POST /upload` if you want cleaner separation). Document **double-submit** behavior (ignore or queue second job — pick one; see `TODOS.md` E4).
3. **EPIC 8 — Download security:** Validate `filename` is a **basename** under `outputs/` only (no `..`, no absolute paths).
4. **Secrets:** Prefer **`OPENAI_API_KEY` env var**; keep `settings.yaml` key empty in template + `.gitignore` for local overrides; README warns never to commit keys.
5. **Batching unit of work:** Clarify in code that a **batch** is “chunk of work sent in one API call” — likely **(event × enabled templates)** rows, capped by `batch_size` **tokens/rows** — define in generation module so retries are coherent.

### Architecture (boundaries)

ASCII — end-to-end flow:

```
  schedule.xlsx     stats.xlsx          templates/*.json
        \              |                      |
         \             |    settings.yaml     |
          \            |         |              |
           v           v         v              v
        +---------------------------------------------+
        | InputParser (MLB)    TemplateRegistry      |
        |   -> normalized      -> enabled ids        |
        |       events              |                |
        +---------------------------|----------------+
                                    v
                          +-------------------+
                          | PromptBuilder      |
                          |  generation_mode   |
                          |  = "template"      |
                          +---------+---------+
                                    v
                          +-------------------+
                          | OpenAI batches     |
                          | (structured JSON)  |
                          +---------+---------+
                                    v
                          +-------------------+
                          | RowAssembler       |
                          | + DateRuleEngine   |
                          +---------+---------+
                                    v
                          +-------------------+
                          | QA + Dedupe        |
                          +---------+---------+
                                    v
                          +-------------------+
                          | CSV writers        |
                          | outputs/ …         |
                          +-------------------+

  Flask:  POST /run -----> start job in thread
          GET  /run/status/<id> ---> read job state
          GET  /download/<file> ---> safe path only
```

**Production-style failure:** OpenAI 429/5xx mid-batch → plan already says log and continue; **add:** exponential backoff + cap, and **persist partial CSV** only if spec allows — otherwise all rows for failed batch → recoverable error in summary.

### Code quality (plan-level)

- **DRY:** One `Row` / schema definition consumed by validator + CSV writer + (optional) Pydantic model for LLM parse.
- **Explicit:** One function `run_pipeline(settings_path) -> RunResult` used by CLI tests and Flask job wrapper — **no duplicated orchestration**.

### Test review

See **test plan file** for routes and E2E scope. Target **pytest**; **mock OpenAI** in default CI; **golden xlsx fixtures** in `tests/fixtures/`. Mark **LLM wording** checks as `[→EVAL]` (small fixed batch), not blocking unit CI.

**Coverage intent:** Parsers, date engine, QA, download safety, and job lifecycle should reach **★★★** on critical branches; Flask flow at least one **[→E2E]** or scripted manual checklist before handoff.

### Performance

- **Sequential batches** are acceptable for Phase 1; document expected runtime ~ `(#batches × latency)`.
- **Optional later:** parallel batches with `asyncio` + semaphore — **NOT in scope** unless client needs speed.

### NOT in scope (eng review)

- Hosted deployment, auth, multi-tenant UI, Celery/Redis, cron, real-time sports APIs.

### What already exists

- **No application code** in this workspace yet — only planning artifacts and gstack skills under `.cursor/skills/`.

### Failure modes → tests / handling

| Failure | Test? | User-visible? |
| ------- | ----- | ------------- |
| Truncated LLM JSON | Structured output + retry | Summary shows batch failed |
| Hallucinated player in options | Validator rejects | Row in `errors.csv` |
| Path traversal on download | Unit | 404 or 400 |
| Double-click Generate | Integration/E2E | Second run blocked or queued (define) |
| Empty inputs | Parser validator | Clear error before spend |

**Critical gap if unimplemented:** **download path traversal** and **unbounded synchronous POST** — **mitigated** by amendments above + decision **B**.

### Outside voice (Codex)

Skipped — `codex` CLI not available in this environment.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (plan) | Structured outputs + job/poll + download hardening + test plan; see section above |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

**UNRESOLVED:** Client open questions (Topic Import ID, timezone, near-dup policy) — listed in Epic + `TODOS.md` E6.

**VERDICT:** **Eng plan review complete** — implement with amendments and `TODOS.md`. Optional next: **`/plan-design-review`** for Flask single-page UX (progress, errors, empty states). Run **`/ship`** when code exists and diff-scoped reviews apply.
