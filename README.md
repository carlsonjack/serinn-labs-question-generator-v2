# Serinn Labs — Structured Content Generation

Local Python app that turns sports schedule / stats spreadsheets into upload-ready CSV question rows (MLB, MLS, World Cup–style layouts, F1, WNBA, etc.). See **`# Epic: Structured Content Generation Sy.md`** for scope, architecture, and delivery checklist.

---

## Quick start

From the project root:

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Open the URL printed in the terminal (default [http://127.0.0.1:5000/](http://127.0.0.1:5000/)).

**Windows (PowerShell)** — use these instead of the second line above:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

**First-time API key:** copy [`.env.example`](.env.example) to `.env` and set your OpenAI key. You own this key and can rotate it anytime in `.env`:

```bash
cp .env.example .env
# edit .env → OPENAI_API_KEY=sk-...
```

The app loads `.env` automatically on startup. An `OPENAI_API_KEY` in the environment or `.env` overrides `openai_api_key` in [`config/settings.yaml`](config/settings.yaml).

In the UI: pick the **input package**, set **date range** / **topic import id** / **subcategory label** as needed, **upload** `.xlsx` files (and run **Save uploads + create normalizer profile** once if you use a new layout), enable templates, then **generate** and download the CSV.

---

## Operations guide

Everything you need to install, run, troubleshoot, back up, and move this system.

### Required software

| Software | Purpose |
|----------|---------|
| **Python 3.10+** (3.11 recommended) | Runtime |
| **pip** | Installs Python packages from `requirements.txt` |
| **Git** | Clone and update the repository |

No database server, Docker, or Node.js is required for local use.

### Dependency versions

Pinned in [`requirements.txt`](requirements.txt):

| Package | Version range |
|---------|---------------|
| openai | ≥ 1.59.0, &lt; 2 |
| pandas | ≥ 2.0.0, &lt; 3 |
| openpyxl | ≥ 3.1.0, &lt; 4 |
| flask | ≥ 3.0.0, &lt; 4 |
| pyyaml | ≥ 6.0.0, &lt; 7 |
| python-dateutil | ≥ 2.9.0, &lt; 3 |
| jinja2 | ≥ 3.1.0, &lt; 4 |
| python-dotenv | ≥ 1.0.0, &lt; 2 |
| pytest | ≥ 7.4.0, &lt; 8 (dev/tests only) |
| vercel | ≥ 0.5.0, &lt; 0.6 (optional; Vercel Blob sync) |

Check your Python version: `python3 --version` or `python --version`. Install from [python.org/downloads](https://www.python.org/downloads/) if needed.

### Supported operating systems

| OS | Supported | Notes |
|----|-----------|-------|
| **macOS** | Yes | Primary local workflow. Use `source venv/bin/activate`. |
| **Windows** | Yes | Use `venv\Scripts\Activate.ps1` (PowerShell) or `venv\Scripts\activate.bat` (cmd). |
| **Linux** | Yes | Same commands as macOS. |

This is a **local desktop workflow** — you run `python main.py` on your own machine and use the browser UI. An optional **Vercel** deployment exists for hosted use (see [Infrastructure](#infrastructure) below).

### Installing and updating dependencies

**Install (first time or after clone):**

```bash
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Update to latest allowed versions:**

```bash
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --upgrade
```

**If the environment is corrupted:** delete the `venv/` folder and recreate it with the install commands above.

### Dependency failures — diagnose and fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `python: command not found` | Python not installed or not on PATH | Install Python 3.10+; on macOS try `python3.11` explicitly |
| `No module named 'flask'` (or similar) | Virtualenv not activated or deps not installed | `source venv/bin/activate` then `pip install -r requirements.txt` |
| `Requires-Python >=3.10` | Python too old | Upgrade Python |
| `pip` errors / build failures | Stale pip or network issue | `pip install --upgrade pip` and retry; check internet connection |
| Permission errors on `pip install` | Installing outside venv | Always activate `venv` first |

### Service startup failures — diagnose and fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Missing config file: config/settings.yaml` | Running from wrong directory or missing config | Run from project root; restore `config/settings.yaml` from git |
| `Address already in use` | Port 5000 taken | Set `PORT=5001` in `.env` or stop the other process |
| App exits immediately | Uncaught import error | Read the full traceback; reinstall deps (see above) |
| Browser cannot connect | Wrong host/port or firewall | Use the exact URL printed by `python main.py`; default is `http://127.0.0.1:5000/` |

Optional env vars (in `.env` or shell): `HOST`, `PORT`, `FLASK_DEBUG` — see [`.env.example`](.env.example).

### Incorrect output — diagnose and fix

After **Generate**, the UI shows a QA summary (row counts, validation failures, duplicates). Download the **output CSV** and any **errors CSV** linked from the run.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Zero questions generated | **Date filter** excludes all events | Widen `date_filter.start` / `date_filter.end` in settings or the UI |
| Wrong **topic_import_id** on rows | Step 6 / settings mismatch | Set `topic_import_id` in the UI or [`config/settings.yaml`](config/settings.yaml) |
| Wrong teams or missing players | Schedule/stats **team label mismatch** | Update [`config/team_aliases/`](config/team_aliases/) for that league |
| Empty answer options for player questions | Stats column name mismatch | Check template `stat_column` matches the normalized stats header (e.g. `PTS`, `HR`) |
| Unexpected wording | LLM enabled | Default sports path is local (`event_generation.use_llm: false`); set `true` only if you want OpenAI to polish wording |

See [How to use this properly](#how-to-use-this-properly-simple-map) for how inputs, templates, and export settings connect.

### Normalization failures — diagnose and fix

Normalization turns uploaded `.xlsx` files into parsed events and stats. Failures appear in the UI under **Save uploads + create normalizer profile** or in the generate status line.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No event rows in range` | All schedule dates outside **date_filter** | Widen the date window in settings/UI |
| `All schedule row(s) failed to parse` | Column mapping wrong in normalizer profile | Re-upload; check saved profile under `config/input_profiles/normalizers/` |
| `No data rows under the detected header` | Wrong sheet or empty file | Confirm the workbook matches the expected layout; check file is `.xlsx` |
| Stats not joining to events | Team alias missing | Add aliases in `config/team_aliases/<league>.yaml` |
| Wrong event times | Timezone not set | Set `event_datetime.timezone` in the normalizer profile, or rely on cached team→IANA lookups (requires API key) |

### Upload failures — diagnose and fix

**Input file uploads (schedule/stats):**

| Symptom | Fix |
|---------|-----|
| Red error text in the upload area | Read the message; usually wrong file type, missing slot, or save permission issue |
| Upload succeeds but generate finds no files | Confirm `inputs.category_key` matches the package you configured and files landed in `inputs/` |

**Template uploads (JSON / CSV / Excel):**

| Symptom | Fix |
|---------|-----|
| Per-file error in upload feedback | Fix the listed column/validation issue (missing `template_id`, bad `answer_type`, etc.) |
| `Duplicate template id in upload` | Each template `id` must be unique in one upload batch |
| `resolution_date_rule` compile error | Set a valid `OPENAI_API_KEY` in `.env`, or author `resolution_date_spec` by hand in JSON |
| Nothing saved | Every row failed validation — read the error list; see [Template upload files](#template-upload-files-plain-english) |

### Template compatibility issues — diagnose and fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Template not offered / zero matches | **`subcategory`** does not match input package | Template `subcategory` must normalize to the same key as `inputs.category_key` (case-insensitive) |
| Template skipped during generate | Disabled in **`templates_enabled`** | Set that template id to `true` in settings or re-upload to enable |
| `entity_stat` validation error | Missing `stat_column` or `requires_entities: true` | Fill required columns per [Question family](#question-family--what-each-value-means) |
| Package alias confusion | Template label ≠ input key | Add `inputs.package_aliases` in settings (e.g. `formula_one: [F1, Formula 1]`) |

### Package persistence — diagnose and fix

An **input package** is the combination of `inputs.category_key`, slot filenames under `inputs.files`, uploaded files on disk, and any saved normalizer profile.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Settings revert unexpectedly | Edited wrong file | Local truth: `config/settings.yaml` (+ optional gitignored `config/settings.local.yaml`) |
| Uploaded `.xlsx` missing after restart | Files not saved to `inputs/` | Re-upload; confirm `inputs/` contains the expected filenames |
| Normalizer profile lost | Profile not saved | Run **Save uploads + create normalizer profile** after upload |
| **Vercel deploy:** data disappears between requests | Ephemeral `/tmp` without Blob | Link Vercel Blob and set `BLOB_READ_WRITE_TOKEN` (auto-provisioned on Vercel when Blob is linked) |

Locally, mutable data lives under the repo: `inputs/`, `outputs/`, `templates/` (uploaded), `config/settings.yaml`, and `config/input_profiles/`. These paths are gitignored for user data except bundled config/templates in the repo.

### Outages — diagnose and fix

| Service | When it matters | What to do |
|---------|-----------------|------------|
| **OpenAI API** | Template `resolution_date_rule` compile, optional LLM wording, timezone inference | Check [platform.openai.com](https://platform.openai.com) status; verify billing/quota; confirm key in `.env` |
| **Local app** | Always | Restart: `Ctrl+C`, then `python main.py` again |
| **Vercel** (if deployed) | Hosted UI | Check [vercel-status.com](https://www.vercel-status.com); redeploy from dashboard if needed |

Default **sports generation does not call OpenAI** (`event_generation.use_llm: false`). You can generate schedule/stats questions without a working API key unless you use the optional features above.

### Backup and restore

**What to back up:**

| Path | Contents |
|------|----------|
| `.env` | API key and local server settings (not in git) |
| `config/settings.yaml` | Active configuration |
| `config/settings.local.yaml` | Optional local overrides (if present) |
| `config/input_profiles/` | Normalizer profiles |
| `inputs/` | Uploaded workbooks |
| `outputs/` | Generated CSVs |
| `templates/` | Uploaded/custom templates |
| `config/team_aliases/` | Custom team alias edits |

**Restore:** copy these paths back into a fresh clone, recreate `venv`, run `pip install -r requirements.txt`, and start the app.

**On Vercel with Blob:** user data is mirrored to Vercel Blob when `BLOB_READ_WRITE_TOKEN` is set. Back up via the Vercel dashboard or export blobs; local git clone alone does not include Blob-stored uploads.

### Migrating to another machine

1. Clone or copy the repository.
2. Copy `.env`, `config/`, `inputs/`, `outputs/`, and `templates/` from the old machine (see backup table).
3. On the new machine:

   ```bash
   python3.11 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python main.py
   ```

4. Open the UI and confirm the input package, date range, and a test generate.

Same OS not required — macOS ↔ Windows works if you use the correct venv activation command.

### Infrastructure

| Mode | What runs | Persistence |
|------|-----------|-------------|
| **Local (default)** | Flask dev server on your machine (`python main.py`) | Files on disk under the project directory |
| **Vercel (optional)** | Serverless Python function + static UI | `/tmp` per instance; durable data via **Vercel Blob** when linked |

No load balancer, queue, or separate worker process is required for local operation.

### Databases

**None.** All state is file-based: YAML settings, JSON templates, JSON/YAML profiles, `.xlsx` inputs, and CSV outputs.

### Third-party services

| Service | Required? | Used for |
|---------|-----------|----------|
| **OpenAI** | Optional for default sports runs | `resolution_date_rule` compilation on template upload; optional event wording (`event_generation.use_llm: true`); home-team timezone inference when timezone unset |
| **Vercel Blob** | Only on Vercel deploy with persistence | Mirrors uploads, settings, outputs between serverless invocations |
| **Vercel hosting** | Optional | Hosted deployment alternative to local |

### Hosting environment

- **Day-to-day operation:** your Mac or Windows PC, localhost browser UI.
- **Optional production:** Vercel serverless (see `core/data_layout.py` and `core/blob_store.py`).

### Credentials, config, and access

| Item | Required? | Where |
|------|-----------|-------|
| **`OPENAI_API_KEY`** | Optional (required for some template/LLM features) | `.env` — **you own and rotate this key** |
| **`config/settings.yaml`** | Yes | Committed defaults; UI writes changes here |
| **`config/settings.local.yaml`** | No | Gitignored local overrides |
| **`.env`** | Recommended | `OPENAI_API_KEY`, `HOST`, `PORT`, `FLASK_DEBUG`; optional `BLOB_READ_WRITE_TOKEN` on Vercel |
| **[`.env.example`](.env.example)** | Reference | Template for variable names |
| **Admin / cloud access** | Local: none beyond your machine | Vercel: your Vercel account if deployed |

Never commit real API keys in tracked files. Prefer `.env` for secrets.

---

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
| `topic_import_id` | **Source of truth** — set in Step 6 (Topic Import ID) or in `settings.yaml`. Used on every generated row for the active package. |
| `topic_import_ids.<package>` | Optional fallback when `topic_import_id` is empty. Keys are **lowercase** package ids (`mlb`, `world_cup`, `mls`, …). |

Example: Step 6 set to `mlb-mlb-season-2026` → every row uses that ID, even if `topic_import_ids.mlb` is still `mlb-regular-season`.

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

### Sports / events generation (no OpenAI by default)

For schedule + stats packages (MLB, WNBA, MLS, etc.), question text and answer options are filled **locally from templates** unless you opt in to LLM wording:

| Setting | Default | Meaning |
|---------|---------|---------|
| `event_generation.use_llm` | `false` | Fill `{home_team}`, `[HOME_TEAM]`, `{entity_options}`, etc. in code — **no API key required** to generate. |
| `event_generation.use_llm` | `true` | Batched OpenAI calls polish question wording (requires `openai_api_key`). |

OpenAI may still be used for **other** steps: compiling `resolution_date_rule` on template upload, and **home-team timezone inference** when the saved normalizer profile leaves `event_datetime.timezone` unset (e.g. WNBA). Those are separate from event question generation.

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
- **Export Topic Import ID:** Set in Step 6 (`topic_import_id` in settings). Optional `topic_import_ids.<package>` entries in `config/settings.yaml` are fallbacks only when Step 6 is empty.
- **Calendar-style event labels:** Normalizers may set `event_display` on `NormalizedEvent`; the CSV `event` column uses it when present (otherwise `Away vs Home`).

### Field competitions (golf, F1)

Some sports have **tournament calendars** instead of home/away matchups. Configure `inputs.packages.<pkg>.competition_format: field`:

- **Schedule:** map `event_name` / `start_date`; no home/away columns required.
- **Stats (optional):** global rankings without a `TEAM` column — all players get a synthetic field code (default `FIELD`).
- **Templates:** use `{event_name}` for tournament labels; `entity_stat` uses `top_n_per_team` as **top N in the entire field**.
- **Ascending stats:** set `ascending_stat_columns` (e.g. `RANK`) when lower values are better.

Registered field normalizers: `f1`, `golf`.

See [`config/settings.yaml`](config/settings.yaml) for a commented example with both `mlb` and `F1`.

---

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
| `venv/bin/python -m pytest` | Full default suite. Exhaustive/live checks are skipped unless explicitly enabled. |
| `venv/bin/python -m pytest -m integration` | Parser registry, bundle loading, and deterministic pipeline matrix tests. |
| `venv/bin/python -m pytest -m "not needs_local_inputs and not live_openai and not exhaustive"` | CI-safe gate excluding local client files, live OpenAI, and exhaustive-only cases. |
| `RUN_EXHAUSTIVE_TESTS=1 venv/bin/python -m pytest -m exhaustive` | Pre-delivery edge-case matrix expansion. |
| `RUN_LIVE_OPENAI_TESTS=1 OPENAI_API_KEY=... venv/bin/python -m pytest -m live_openai` | Optional live provider smoke tests when such tests exist. |

Factories for `.xlsx` files live in [`tests/fixtures/workbooks.py`](tests/fixtures/workbooks.py). Add new vertical checks beside [`tests/integration/test_f1_bundle_load.py`](tests/integration/test_f1_bundle_load.py).

## Status

Repository initialized; implementation follows the Epic (EPIC 1+).
