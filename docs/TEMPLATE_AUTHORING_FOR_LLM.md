# Template authoring guide (for Claude / ChatGPT)

Use this document when you are asked to **create question templates** (CSV or Excel) for the Serinn Labs question generator. The app reads templates, joins them to **schedule** and/or **stats** spreadsheets, and exports one CSV row per game (or per content unit).

**Typical user prompt:**

> Create 10 WNBA questions. I attached `schedule.xlsx` and `stats.xlsx`. Follow the template column guide. Start date = 24 hours after event time; expiration = 2 days after event; resolution = January 15 (of the event year).

---

## Before you write templates

| Input | Required for | Notes |
|--------|----------------|-------|
| **Schedule** (`event_source` / `schedule.xlsx`) | `event` and `entity_stat` | One row per game or tournament; team sports use home/away columns; **field sports** (golf, F1) use `event_name` + date. |
| **Stats** (`metric_source` / `stats.xlsx`) | `entity_stat` only | Team sports: player rows with a **TEAM** code. **Field sports:** global rankings without `TEAM` (e.g. world rankings). |
| **`subcategory`** | All sports templates | Must match the package (e.g. `WNBA` for package `wnba`). |
| **`openai_api_key`** (in app settings) | Optional | Needed to **compile** natural-language `*_date_rule` columns on upload if you do not ship pre-built `*_date_spec` JSON. |

---

## Two question types (sports)

### 1. Schedule / event questions (`question_family` = `event`)

Questions about the **game or teams** (winner, yes/no props, totals wording). Answers come from text **you write** in the template—not from the stats file.

| Field | What to put |
|--------|-------------|
| **`question_family`** | `event` |
| **`requires_entities`** | `false` (or blank → treated as false for event) |
| **`stat_column`** | **Leave empty / omit** |
| **`top_n_per_team`** | **Leave empty / omit** |
| **`question`** | Use `{home_team}` and `{away_team}` (or `[HOME_TEAM]` / `[AWAY_TEAM]`) for team names from the schedule. |
| **`answer_options`** | For winner MC: `{home_team}||{away_team}`. For yes/no: `Yes||No` or leave blank (app fills `Yes||No`). |

**Example (JSON):** [`templates/WNBA-010.json`](../templates/WNBA-010.json)  
**Example (CSV block):** [`samples/wnba_schedule_game_winner_one_question.csv`](../samples/wnba_schedule_game_winner_one_question.csv)

### 2. Player / stat questions (`question_family` = `entity_stat`)

Questions where answer choices are **player names** from the stats workbook.

| Field | What to put |
|--------|-------------|
| **`question_family`** | `entity_stat` |
| **`requires_entities`** | `true` |
| **`stat_column`** | **Required.** Spreadsheet column header from stats data (normalized), e.g. `PTS`, `REB`, `HR`, `GOAL_PROBABILITY`, `FG%`. |
| **`top_n_per_team`** | **Required in practice.** Integer: how many top players **per team** (home + away) to include, e.g. `2` → up to 4 names in the option list. Default in app is `2` if omitted on wide-table upload. |
| **`question`** | Game context: `Which player will score the most points in {home_team} vs {away_team}?` |
| **`answer_options`** | **`{entity_options}`** only (or leave blank on wide upload → app sets `{entity_options}`). |

**Example (CSV):** [`samples/wnba_entity_points_one_question.csv`](../samples/wnba_entity_points_one_question.csv)

Schedule team labels must resolve to stats **TEAM** codes (e.g. `Los Angeles Sparks` → `LA`). See [`config/team_aliases/README.md`](../config/team_aliases/README.md). **Field sports (golf):** omit team columns; use `{event_name}` and rank by spreadsheet stat columns (e.g. `AVG POINTS`, `RANK`).

---

## Field competitions (golf, F1-style calendars)

When there is no home/away team:

| Field | Value |
|--------|--------|
| **`question`** | Use `{event_name}` for the tournament (from schedule `event_name`). |
| **`answer_options`** (event) | Placeholders or yes/no until pairing data exists. |
| **`stat_column`** | Spreadsheet column from rankings, e.g. `AVG POINTS`, `RANK`. |
| **`top_n_per_team`** | Top **N in the entire field** (not per team). |

---

## CSV / Excel layouts

**For `.xlsx` / `.xls` and most multi-template CSVs, use Layout A only.**  
Do **not** build Excel with alternating “field name row / value row” pairs (Layout B). That pattern is for small hand-edited CSV files only. If upload fails with *“header/value row pairs (an even number of non-empty rows)”*, the sheet is Layout A but was parsed as Layout B — fix the header row (see below).

### Layout A — Wide table (required for Excel)

**One header row**, then **one row per template** (20 templates ⇒ 21 rows total including the header).

**Required header columns** (names are flexible):

- `template_id` **or** `id`
- `question` **or** `question_template` (both work; prefer `question` to match JSON)
- `answer_type`

| Column | Required? | Notes |
|--------|-----------|--------|
| **`template_id`** or **`id`** | Yes | Unique id, e.g. `WNBA-010`. |
| **`subcategory`** | Yes | `WNBA`, `MLB`, `World Cup`, etc. |
| **`question_template`** or **`question`** | Yes | Question text with placeholders. |
| **`answer_type`** | Yes | `yes_no` or `multiple_choice`. |
| **`answer_options_pattern`** / **`answer_options`** | MC: required pattern; yes_no: optional | Use `||` between choices. |
| **`question_family`** | Recommended | `event` or `entity_stat`. If blank and `stat_column` is set → `entity_stat`. |
| **`requires_entities`** | Recommended | `false` for event; `true` for entity_stat. |
| **`stat_column`** | entity_stat only | e.g. `PTS` |
| **`top_n_per_team`** / **`top_n`** | entity_stat only | e.g. `2` |
| **`priority`** | Optional | Number or empty. |
| **`start_date_rule`** | Optional | Plain English; compiled on upload if API key set. |
| **`expiration_date_rule`** | Optional | Plain English. |
| **`resolution_date_rule`** | Optional | Plain English. |
| **`_comment`** / **`notes`** | Optional | For humans only. |

### Layout B — Block CSV (two rows per template) — not for bulk Excel

Row 1 = field names, row 2 = values, repeat. **Only use for `.csv` with a handful of templates**, not for 10+ row Excel exports.

```csv
id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities
WNBA-010,WNBA,event,Who will win {home_team} vs {away_team}?,multiple_choice,{home_team}||{away_team},1,false
```

Same columns as JSON templates: `stat_column`, `top_n_per_team`, `start_date_rule`, etc.

---

## Column reference by `question_family`

### Shared columns (all sports templates)

| Column | Required | Values / notes |
|--------|----------|----------------|
| **`id`** / **`template_id`** | Yes | Unique string. |
| **`subcategory`** | Yes | Package label; must match inputs package (case-insensitive). |
| **`question_family`** | Yes* | `event`, `entity_stat`, `content`, `stock`. *Can infer entity_stat if `stat_column` present. |
| **`question`** | Yes | Final wording with placeholders filled at generation time. |
| **`answer_type`** | Yes | `yes_no` \| `multiple_choice`. |
| **`answer_options`** | Depends | See below. |
| **`priority`** | Yes in JSON | Integer or empty string in CSV. |
| **`requires_entities`** | Yes in JSON | Boolean: `false` for event; `true` for entity_stat. |

### `event` only — leave these **empty**

| Column | Value |
|--------|--------|
| **`stat_column`** | omit |
| **`top_n_per_team`** | omit |
| **`line`** | omit unless question uses `{line}` / totals |
| **`timeframe`** | omit unless used by custom templates |

### `entity_stat` only — fill these

| Column | Value |
|--------|--------|
| **`stat_column`** | Spreadsheet column header (normalized), e.g. `PTS`, `HR`, `FG%` |
| **`top_n_per_team`** | e.g. `2` |
| **`requires_entities`** | `true` |

### Date columns (optional; sports `event` / `entity_stat`)

Three independent timings per output row: **Start Date**, **Expiration Date**, **Resolution Date** (ISO 8601 in export).

| Column | Role | Example natural language (`*_date_rule`) |
|--------|------|----------------------------------------|
| **`start_date_rule`** | When the question opens | `24 hours after event start` |
| **`expiration_date_rule`** | When trading/entry closes | `2 days after event start` |
| **`resolution_date_rule`** | When the market resolves | `January 15 of the event calendar year` |

On upload, non-empty rules are compiled to `*_date_spec` JSON (needs `openai_api_key`) unless you author JSON yourself.

**Equivalent structured specs (no API needed if you save JSON templates):**

| Intent | `kind` | Key fields |
|--------|--------|------------|
| Start 24h after tip | `offset_from_anchor` | `anchor`: `event_datetime`, `offset_hours`: `24` |
| Expire 2 days after tip | `offset_from_anchor` | `anchor`: `event_datetime`, `offset_days`: `2` |
| Resolve Jan 15 (event year) | `calendar_in_year` | `calendar_month`: `1`, `calendar_day`: `15`, `year_policy`: `event_year` |

If date rule columns are **empty**, the app uses [`config/settings.yaml`](../config/settings.yaml) → `date_rules` (per subcategory).

---

## Worked example: 10 WNBA schedule questions

User wants **schedule-only** winner questions (no stats). You only need **one template**; the app emits **one row per game** in the date window.

1. **Template id:** `WNBA-010` (or ten ids if wording differs per row—usually one template is enough).
2. **`question_family`:** `event`
3. **`requires_entities`:** `false`
4. **Do not set** `stat_column` or `top_n_per_team`.
5. **`question`:** `Who will win {home_team} vs {away_team}?`
6. **`answer_options`:** `{home_team}||{away_team}`
7. **Dates** (block CSV example):

```csv
id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,start_date_rule,expiration_date_rule,resolution_date_rule
WNBA-010,WNBA,event,Who will win {home_team} vs {away_team}?,multiple_choice,{home_team}||{away_team},1,false,24 hours after event start,2 days after event start,January 15 of the event calendar year
```

8. Tell the operator: set **`inputs.category_key`** to `wnba`, upload **schedule only**, enable template **`WNBA-010`**, run Generate.

For **10 different wordings** (e.g. “Will {away_team} beat {home_team}?”), create **10 template rows** with different `id`s, all `question_family` = `event`, all without `stat_column`.

---

## Worked example: WNBA points leader (needs stats)

```csv
id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,stat_column,top_n_per_team,start_date_rule,expiration_date_rule,resolution_date_rule
WNBA-002,WNBA,entity_stat,Which player will score the most points in {home_team} vs {away_team}?,multiple_choice,{entity_options},1,true,PTS,2,event_date_minus_48_hours,2 days after event start,January 15 of the event calendar year
```

Requires **both** schedule and stats files.

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Excel upload: *even number of non-empty rows* | You used **Layout A** but the app did not recognize the header. Ensure the first row includes **`template_id`** (or `id`), **`question`** (or `question_template`), and **`answer_type`**. One data row per template — not two-row blocks. |
| `entity_stat` without `stat_column` | Add `stat_column` or change to `event`. |
| `event` with `stat_column` / `top_n_per_team` | Remove those columns; they are ignored and confuse authors. |
| `requires_entities: true` on a winner question | Use `false` for `event`. |
| `{entity_options}` on an `event` template | Use explicit team names or `Yes||No`. |
| Bare `Los Angeles` in schedule without team map | Use full team names from schedule (`Los Angeles Sparks`). |
| Mismatched `subcategory` | `WNBA` templates only run when package is `wnba`. |

---

## JSON template (single file per template)

Save under `templates/<id>.json`. Same fields as CSV. Example: [`templates/WNBA-010.json`](../templates/WNBA-010.json).

---

## Operator checklist (paste into your reply)

1. Templates use `subcategory` = package name (`WNBA`).
2. Schedule-only → `question_family` = `event`, no `stat_column` / `top_n_per_team`.
3. Player props → `entity_stat` + `stat_column` + `top_n_per_team` + stats file.
4. Enable template ids in `templates_enabled` in settings (or UI).
5. Upload templates via UI **Templates** step (CSV/XLSX/JSON).

For machine-readable team aliases and package keys, see [`config/team_aliases/README.md`](../config/team_aliases/README.md) and the main [`README.md`](../README.md).
