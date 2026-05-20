# Serinn Labs — Structured Content Generation

Local Python app that turns sports schedule / stats spreadsheets into upload-ready CSV question rows (MLB, MLS, World Cup–style layouts, F1, etc.). See **`# Epic: Structured Content Generation Sy.md`** for scope, architecture, and delivery checklist.

## How to use this properly (simple map)

Everything below connects **inputs** → **templates** → **export**. If one link is wrong, you get empty runs, wrong topic IDs, or templates that never appear.

### 1. Pick an **input package**

In [`config/settings.yaml`](config/settings.yaml), `inputs.category_key` chooses which block under `inputs.files` is active (e.g. `world_cup`, `mlb`, `MLS`). That same key drives **which templates** are allowed (see step 4).

### 2. Put files where `inputs.files` says they should go

For each slot (`event_source`, `metric_source`, `schedule`, `stats`, …) the value is the **filename** that must live under your inputs directory (default `inputs/`). Upload those files in the UI (**Save uploads + create normalizer profile**) or copy them in manually. For schedule/event-only templates (e.g. game winner), you can upload only the schedule slot; the metric slot stays optional until you run player-stat templates.

### 3. **Topic import ID** (where questions land downstream)

Generated CSV rows include a **`topic_import_id`** column. That value comes from settings—not from template ids:

| Setting | Meaning |
|--------|---------|
| `topic_import_ids.<package>` | Per-package override. Keys are **lowercase** package ids (`mlb`, `world_cup`, `mls`, …). When present for the active package, this wins. |
| `topic_import_id` | Fallback when there is no entry for the active package. |

Example: active package `world_cup` → use `topic_import_ids.world_cup` if set; else `topic_import_id`.

**Template `id`** (e.g. `world_cup_event_winner_mc`) is only the template’s name and `templates_enabled` switch—it is **not** the topic import id.

### 4. **Templates**: `id` vs `subcategory` vs config “Subcategory label”

| Field | What it does |
|--------|----------------|
| **`id`** | Unique template name; used in `templates_enabled` to turn templates on/off. |
| **`subcategory`** (on each template) | Two jobs: (1) **Match the input package** after normalization (e.g. `World Cup` ↔ `world_cup`). (2) **Printed on every CSV row** in the `subcategory` column for questions built from that template. |
| **`subcategory`** in `settings.yaml` (UI: “Subcategory label”) | Display/filename hint and fallback when the app infers a label for the package—it does **not** replace each template’s `subcategory` on export rows. |

Matching rule: labels are compared in a **normalized** form (case-insensitive; spaces/punctuation stripped), so `World Cup`, `world_cup`, and `WORLD_CUP` line up with package `world_cup`.

### 5. **Date filter** and **date rules**

- **`date_filter.start` / `date_filter.end`**: Only events (and thus questions) in that window are considered.
- **`date_rules`**: Offsets for start / expiration / resolution on each row. Keys under `date_rules` can follow **`date_rules.default`** plus overrides; row assembly uses the template’s subcategory (lower case) when resolving rules—add a block if you need custom offsets for a new vertical.
  - **`resolution_offset_anchor`**: `kickoff` (default) keeps `resolution_date = event_datetime + resolution_offset_hours`. Use `expiration` to compute `resolution_date = expiration_datetime + resolution_offset_hours` (after applying `expiration_offset_hours`), which matches “resolve X hours after the question expires” when those times differ from kickoff.
- **Event times & timezones (declarative schedules)**: If the normalizer maps separate date + time columns, a missing time defaults to **00:00:00**. When `event_datetime.timezone` is set in the saved profile (IANA like `America/New_York`, or legacy `EST`), that wall time is interpreted in that zone and stored as **naive UTC** on `NormalizedEvent.event_datetime`. If `timezone` is unset but `openai_api_key` is configured, the app batches **home team → IANA** lookups via OpenAI and merges them into [`config/event_team_timezone_cache.json`](config/event_team_timezone_cache.json) for repeat runs.

### 6. Enable templates

Templates are **enabled by default**. Uploading via the UI sets each template id to `true` in `templates_enabled`. To skip a template during generation, set its id to `false` in `templates_enabled`.

### 7. New / custom workbook layouts — AI normalizer

For a package without a built-in Python normalizer, use the UI flow: upload inputs → **Save uploads + create normalizer profile** (proposes a declarative spec, previews, saves under `config/input_profiles/normalizers/`). Then generation uses that profile when parsing your `.xlsx` files.

### Template upload files (plain English)

The app accepts **JSON** templates (one file = one template) and **CSV / Excel** uploads with **many templates in one file**. Spreadsheet uploads use one of **two layouts**. If a column is not listed for that layout, you can leave it out.

---

#### Layout A — **Wide table** (one header row, one row per template)

Typical **Excel export**: the first row has column names; each following row is one template.

**Always required**

| Column | What to put |
|--------|-------------|
| **`template_id`** | Short unique id for this template (letters, numbers, dashes). Same idea as `id` in JSON. |
| **`question_template`** | The question text. For sports, you can use `{home_team}` and `{away_team}` where those names should appear. |
| **`answer_type`** | Either **`yes_no`** or **`multiple_choice`**. (The uploader also accepts common synonyms like `binary` / `single_select` and maps them.) |

**Highly recommended**

| Column | What to put |
|--------|-------------|
| **`subcategory`** | Label for this package (e.g. `WNBA`, `MLB`). Should match your **input package** when the app compares names (case-insensitive). If you leave it blank, the app uses **`Content`**. |
| **`answer_options_pattern`** *or* **`answer_options_rule`** | For **multiple choice**, the answer choices separated by **`||`** (two vertical bars), e.g. `Mets||Yankees`. For **yes/no**, you can leave this **blank** for most template types—the app will fill **`Yes||No`** when needed. For **player lists from a stats file**, use **`entity_stat`** (below) and either type **`{entity_options}`** or leave this blank and the app will set `{entity_options}` for you. |
| **`question_family`** | What kind of question this is (see **“Question family”** below). If you leave it blank, the app **guesses** from your text and rules columns. If you put **`stat_column`** without a family, the app treats the row as **`entity_stat`**. |
| **`default_priority`** *or* **`priority`** | Number for ordering (`1`, `2`, …) or leave blank if you do not care. |

**For “pick a player from the stats sheet” templates (`entity_stat`)**

| Column | What to put |
|--------|-------------|
| **`stat_column`** | The **spreadsheet column header** from your stats workbook (normalized), e.g. **`PTS`**, **`HR`**, **`GOAL_PROBABILITY`**, **`FG%`**. It must match the key the parser stores for each player. **Required** for `entity_stat`. |
| **`top_n_per_team`** *or* **`top_n`** | How many top players **per team** (home + away) to offer as choices. If you leave it blank, the app uses **`2`**. |
| **`requires_entities`** | Should be **`true`** or left blank for `entity_stat`. **`false` is not allowed** for `entity_stat`. For any other `question_family`, this must be **`false`** or blank—do not set `true`. |

**Optional extra columns**

| Column | What to put |
|--------|-------------|
| **`template_type`**, **`required_dataset_fields`**, **`notes`** | Free text for your own notes or downstream tooling. |
| **`start_date_rule`**, **`expiration_date_rule`**, **`resolution_date_rule`** | Short text rules for when the question opens, closes, and resolves. If you use **`resolution_date_rule`**, the app may compile it to a structured spec when an API key is set (see **Resolution date rules** below). |
| **`required_input_file`** | Optional; used only to help guess `question_family` when that column is empty. |

---

#### Layout B — **Block CSV** (two rows per template)

**Row 1** = field names. **Row 2** = values. Then **another row 1** + **row 2** for the next template, and so on.

Use the same **ideas** as the table above, but column names match **JSON** style: **`id`**, **`question`**, **`answer_type`**, **`answer_options`**, **`question_family`**, **`requires_entities`**, **`stat_column`**, **`top_n_per_team`**, **`priority`**, etc.

Example: [`samples/template_upload_three_mlb_templates.csv`](samples/template_upload_three_mlb_templates.csv), [`samples/wnba_schedule_game_winner_one_question.csv`](samples/wnba_schedule_game_winner_one_question.csv) (schedule-only), and [`samples/wnba_entity_points_one_question.csv`](samples/wnba_entity_points_one_question.csv) (stats / `entity_stat`).

---

#### Question family — what each value means

| Value | In simple terms |
|--------|-----------------|
| **`event`** | A question about the **game or teams** (winner, spread-style wording, totals bands, etc.). Answer options are fixed text you write in the sheet (or `Yes||No`). The **stats file is not** used to build the answer list. |
| **`entity_stat`** | A question where answers are **real names** (usually players) taken from the **stats** input using **`stat_column`** and **`top_n_per_team`**. Use **`{entity_options}`** as the answer pattern (or leave answer options blank and the uploader sets it). |
| **`content`** | Entertainment / marketing-style templates (albums, movies, etc.), not tied to a single sports event in the schedule row sense. |
| **`stock`** | Stock-market templates (separate client layout). |

**Schedule-only vs stats — which columns to fill**

| Column | `event` (schedule question) | `entity_stat` (player question) |
|--------|----------------------------|----------------------------------|
| **`question_family`** | `event` | `entity_stat` |
| **`requires_entities`** | `false` | `true` |
| **`stat_column`** | omit | required (e.g. `PTS`, `HR`) |
| **`top_n_per_team`** | omit | required in practice (e.g. `2`) |
| **`answer_options`** | `{home_team}||{away_team}` or `Yes||No` | `{entity_options}` |
| **Inputs** | schedule `.xlsx` only is enough | schedule **and** stats `.xlsx` |

WNBA examples: schedule winner → [`templates/WNBA-010.json`](templates/WNBA-010.json) and [`samples/wnba_schedule_game_winner_one_question.csv`](samples/wnba_schedule_game_winner_one_question.csv); player points → [`samples/wnba_entity_points_one_question.csv`](samples/wnba_entity_points_one_question.csv).

**Authoring templates with Claude / ChatGPT:** see [`docs/TEMPLATE_AUTHORING_FOR_LLM.md`](docs/TEMPLATE_AUTHORING_FOR_LLM.md) (column-by-column guide, date-rule examples, and prompt patterns). **Excel uploads** must use **Layout A** (one header row + one row per template); columns can be `question` or `question_template` and `answer_options` or `answer_options_pattern`.

---

#### Answer type and answer options — quick guide

| **`answer_type`** | What to put in answer options |
|-------------------|--------------------------------|
| **`yes_no`** | Best: **`Yes||No`**. If you leave it blank, **`event`** and **`entity_stat`** rows get **`Yes||No`** automatically; **`content`** / **`stock`** can stay blank where the schema allows. |
| **`multiple_choice`** | Usually **`Option A||Option B||Option C`**. For **`entity_stat`**, use **`{entity_options}`** (or leave blank to default). **`event`** rows need either a `||` list, or a single “rule-like” token the app already knows about—otherwise validation may fail. |

---

#### Client “stock template” CSV (different shape)

Some spreadsheets use **capitalized** headers like **`Template ID`**, **`Question Template`**, **`Answer Type`**, **`Answer Options`**, **`Recommended Priority`**. That path is only for the **stock** client format, not for general sports `template_id` tables.

---

### Sample template CSVs

See [`samples/`](samples/) (e.g. [`samples/template_upload_two_world_cup_templates.csv`](samples/template_upload_two_world_cup_templates.csv)) for **Layout B** block examples used by **Upload** in the UI.

### Resolution date rules (`resolution_date_rule`)

Per-template **resolution** timing can be driven by a natural-language column (compiled once at upload) instead of only YAML heuristics or `date_rules` defaults.

| Mechanism | Applies to |
|-----------|------------|
| **`resolution_date_rule`** (string) | Optional on **content** table CSVs, **block** CSV templates, and **JSON** templates for `question_family` **`content`**, **`event`**, or **`entity_stat`**. |
| **`resolution_date_spec`** (object) | Written automatically when you upload with a non-empty `resolution_date_rule` and `openai_api_key` is available. You may also author this JSON by hand to skip compilation. |
| **Stocks** | **`stock`** templates ignore these fields; they are removed when saving stock uploads. |

**Upload behavior**

1. For non-stock templates, if `resolution_date_rule` is non-empty, the UI calls OpenAI to normalize it into `resolution_date_spec` before saving `templates/<id>.json`. If compilation or validation fails, the upload errors for that row.
2. If `resolution_date_rule` is empty and `resolution_date_spec` is absent, behavior is unchanged: **content** uses legacy text heuristics + optional `content.resolution_dates` in settings; **event / entity_stat** keep YAML `date_rules` resolution offsets (start and expiration always still come from `date_rules`).
3. For **sports events**, a spec only **replaces the `resolution_date` column**; start and expiration still come from `date_rules` for the template subcategory.

**What to write in `resolution_date_rule`**

Use plain English. Examples aligned with entertainment uploads:

- `Resolution date should be start_date + 7 days.` (map `start_date` to **release** or **question start** in the compiled spec)
- `Resolution date should be start_date + 180 days.`
- `Resolution date should align with Grammy nomination announcement date. Resolution date should start on November 1 of the calendar year.`
- `Resolution should evaluate days 8-14 after start_date.` (typically compiled as a **window end** anchor)

Sports/event examples can follow the same column; phrase anchors in terms of **kickoff / first pitch / event time** so the model maps them to `event_datetime`. Concrete sport sample rows can be added later.

**Compiled spec (for authors debugging JSON)**

The machine schema lives in [`core/resolution_date_spec.py`](core/resolution_date_spec.py). At a high level, `kind` is one of:

- **`offset_from_anchor`**: `anchor` (`release_date`, `question_start`, `question_expiration`, `metadata_field`, or for events `event_datetime`) plus `offset_days` / `offset_hours`.
- **`calendar_in_year`**: `calendar_month`, `calendar_day`, and `year_policy` (`release_year`, `release_year_plus_1`, `event_year`, `event_year_plus_1`, `static_context_year`).
- **`metadata_date`**: read an ISO/calendar date from entity or event `metadata` via `metadata_key`.
- **`window_end`**: `anchor` + `end_offset_days` (resolution at end of a day-based window).
- **`none`**: keep default resolution behavior for that pipeline.

`metadata_field` requires `metadata_key` (snake_case, e.g. `estimated_nomination_date`, `second_weekend_start_date`).

---

## Team aliases

Schedule and stats workbooks often use different team labels (e.g. `Houston Astros` vs `HOU`, `Los Angeles Sparks` vs `LA`). Per-league maps live under [`config/team_aliases/`](config/team_aliases/) and load automatically when the pipeline joins events to player stats via `resolve_stats_team_code`.

**Registered packages:** `mlb`, `wnba`, `mls`, `nwsl`, `laliga`, `nba`, `nfl`, `nhl`, `ncaaf`, `ncaab` (plus `package_aliases` in each YAML such as `MLS`, `La Liga`, `NBA`). Package keys are matched case-insensitively (`NHL` and `nhl` share the same map).

**College:** canonical codes are full school names; shared mascot nicknames are intentionally omitted to avoid wrong joins.

To add or update a league, edit or add a YAML file and run `python scripts/generate_team_aliases.py` when using the generator. See [`config/team_aliases/README.md`](config/team_aliases/README.md).

---

## Multi-vertical inputs (reference)

- **MLB (legacy):** Under `inputs.files.mlb`, keep `event_source` and `metric_source` filenames (e.g. `schedule.xlsx`, `stats.xlsx`). Set `inputs.category_key` to `mlb`. Both slots remain in settings, but only files you upload are required on disk—schedule-only runs work for event templates without `stats.xlsx`.
- **Additional packages (e.g. F1):** Add `inputs.files.<Package>` with slot ids → target filenames (any `.xlsx` basename per slot). Slots whose ids match a `SourceRole` (`event_source`, `metric_source`, `entity_source`, `reference_source`) or a built-in alias (`schedule`, `stats`, `fixtures`, `roster`, …) are mapped automatically—no `inputs.file_roles` required unless you use opaque slot names. For schedule+stats only, you can reuse the same two-slot ids as MLB with any filenames. Schedule-only packages omit metric slots.
- **Templates:** Each JSON template’s `subcategory` must match the selected input package when normalized (case-insensitive), e.g. `F1` templates with package `F1`.
- **Aliases:** If the input package key should differ from the template label or parser key, add `inputs.package_aliases`, e.g. `formula_one: [F1, Formula 1]`. The alias allows `formula_one` inputs to use `F1` templates and the registered F1 normalizer.
- **New packages (e.g. MLS):** If there is no Python normalizer for your package key yet, configure **both** `event_source` and `metric_source` (or `schedule` + `stats` with role inference) so the pipeline can run the same schedule+stats composition as MLB; detection still uses your package key for saved profiles. Single-file calendar feeds should map with `package_aliases` to `f1` or add a dedicated normalizer.
- **Export Topic Import ID:** Optional map `topic_import_ids` in `config/settings.yaml` (`mlb`, `f1`, …) keyed by lowercase package id; falls back to top-level `topic_import_id`.
- **Calendar-style event labels:** Normalizers may set `event_display` on `NormalizedEvent`; the CSV `event` column uses it when present (otherwise `Away vs Home`).

### Field competitions (golf, F1)

Some sports have **tournament calendars** instead of home/away matchups. Configure `inputs.packages.<pkg>.competition_format: field`:

- **Schedule:** map `event_name` / `start_date`; no home/away columns required.
- **Stats (optional):** global rankings without a `TEAM` column — all players get a synthetic field code (default `FIELD`).
- **Templates:** use `{event_name}` for tournament labels; `entity_stat` uses `top_n_per_team` as **top N in the entire field**.
- **Ascending stats:** set `ascending_stat_columns` (e.g. `RANK`) when lower values are better.

Registered field normalizers: `f1`, `golf`.

See [`config/settings.yaml`](config/settings.yaml) for a commented example with both `mlb` and `F1`.

## Requirements

- **Python 3.10+** (check with `python --version` or `python3 --version`)
- If Python is missing or older than 3.10, install a current release from [python.org/downloads](https://www.python.org/downloads/)

## Setup

### 1. Virtual environment

From the project root:

```bash
python -m venv venv
```

### 2. Activate the virtual environment

**macOS / Linux:**

```bash
source venv/bin/activate
```

**Windows (Command Prompt):**

```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell):**

```powershell
venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. OpenAI API key

**Preferred:** set the environment variable so secrets are not stored in files tracked by git:

**macOS / Linux:**

```bash
export OPENAI_API_KEY="sk-..."
```

**Windows (Command Prompt):**

```cmd
set OPENAI_API_KEY=sk-...
```

**Windows (PowerShell):**

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

If `OPENAI_API_KEY` is set, it overrides any key in [`config/settings.yaml`](config/settings.yaml).

**Optional:** copy values you want to override into `config/settings.local.yaml` (gitignored). Use that file for local tweaks such as `model` or `date_filter`. Do **not** commit real API keys in `settings.yaml` or any tracked file.

See also [`.env.example`](.env.example) for variable names you can set manually (this project does not load `.env` automatically unless you add a loader later).

## Run

```bash
python main.py
```

Open the URL printed in the terminal (default [http://127.0.0.1:5000/](http://127.0.0.1:5000/)). Optional environment variables: `HOST`, `PORT`, `FLASK_DEBUG` (see `.env.example`).

In the UI: pick the **input package**, set **date range** / **topic import id** / **subcategory label** as needed, **upload** `.xlsx` files (and run **Save uploads + create normalizer profile** once if you use a new layout), enable templates, then **generate** and download the CSV.

### Sports / events generation (no OpenAI by default)

For schedule + stats packages (MLB, WNBA, MLS, etc.), question text and answer options are filled **locally from templates** unless you opt in to LLM wording:

| Setting | Default | Meaning |
|---------|---------|---------|
| `event_generation.use_llm` | `false` | Fill `{home_team}`, `[HOME_TEAM]`, `{entity_options}`, etc. in code — **no API key required** to generate. |
| `event_generation.use_llm` | `true` | Previous behavior: batched OpenAI calls polish question wording (requires `openai_api_key`). |

OpenAI may still be used for **other** steps: compiling `resolution_date_rule` on template upload, and **home-team timezone inference** when the saved normalizer profile leaves `event_datetime.timezone` unset (e.g. WNBA). Those are separate from event question generation.

## Adding a new client category

Every new category should be added through the same acceptance contract:

1. Add or update an input profile under [`config/input_profiles/`](config/input_profiles/) if auto-detection cannot infer the workbook shape.
2. Add fixture builders in [`tests/fixtures/workbooks.py`](tests/fixtures/workbooks.py) for representative happy-path and malformed workbooks.
3. Add templates under [`templates/`](templates/) or test-local template fixtures with the intended `subcategory`.
4. Add a `PipelineMatrixCase` in [`tests/fixtures/matrix.py`](tests/fixtures/matrix.py) covering the category’s happy path and at least one failure path.
5. If package names and template labels differ, add `inputs.package_aliases` coverage so the relationship is explicit.
6. Run the deterministic gates below before client handoff.

The shared matrix intentionally uses mocked generation. This proves parser/template/pipeline/output behavior without calling OpenAI; live provider checks are opt-in smoke tests only.

## Testing

| Command | Purpose |
|--------|---------|
| `.venv/bin/python -m pytest` | Full default suite. Exhaustive/live checks are skipped unless explicitly enabled. |
| `.venv/bin/python -m pytest -m integration` | Parser registry, bundle loading, and deterministic pipeline matrix tests. |
| `.venv/bin/python -m pytest -m "not needs_local_inputs and not live_openai and not exhaustive"` | CI-safe gate excluding local client files, live OpenAI, and exhaustive-only cases. |
| `RUN_EXHAUSTIVE_TESTS=1 .venv/bin/python -m pytest -m exhaustive` | Pre-delivery edge-case matrix expansion. |
| `RUN_LIVE_OPENAI_TESTS=1 OPENAI_API_KEY=... .venv/bin/python -m pytest -m live_openai` | Optional live provider smoke tests when such tests exist. |

Factories for `.xlsx` files live in [`tests/fixtures/workbooks.py`](tests/fixtures/workbooks.py). Add new vertical checks beside [`tests/integration/test_f1_bundle_load.py`](tests/integration/test_f1_bundle_load.py).

## Status

Repository initialized; implementation follows the Epic (EPIC 1+).
