# Template authoring guide (for Claude / ChatGPT)

Use this document when you are asked to **create question templates** (CSV or Excel) for the Serinn Labs question generator. The app reads templates, joins them to input spreadsheets (sports schedules, entertainment release lists, stock watchlists, etc.), and exports upload-ready CSV rows.

**Typical user prompts:**

> Create 10 WNBA questions. I attached `schedule.xlsx` and `stats.xlsx`. Follow the template column guide. Start date = 24 hours after event time; expiration = 2 days after event; resolution = January 15 (of the event year).

> Create music release templates for June 2026. Use `[ALBUM_OR_RELEASE]` placeholders. Resolution = start date + 8 days.

> Create daily stock templates. Use `{ASSET}` and `{DATE}` placeholders. Timeframe = Daily.

---

## Core rule: questions must be about future events

**Every question must ask about something that has not happened yet.** Templates are used to generate prediction markets — wording must be forward-looking, not retrospective.

| Do | Don't |
|----|-------|
| `Who will win {home_team} vs {away_team}?` | `Who won {home_team} vs {away_team}?` |
| `Which player will score the most points in …?` | `Which player scored the most points in …?` |
| `Will [ALBUM_OR_RELEASE] debut on the Billboard 200?` | `Did [ALBUM_OR_RELEASE] debut on the Billboard 200?` |
| `Will {ASSET} close higher on {DATE}?` | `Did {ASSET} close higher on {DATE}?` |

Use **future tense** (`will`, `going to`) or neutral forward-looking phrasing. Avoid past tense (`won`, `scored`, `did`, `was`) and questions that assume the outcome is already known.

The app filters which schedule rows, releases, or trading days get output rows by date window — but **question text must still read as a prediction**, even when the underlying event is imminent.

---

## Before you write templates

| Input | Required for | Notes |
|--------|----------------|-------|
| **Schedule** (`event_source` / `schedule.xlsx`) | Sports `event` and `entity_stat` | One row per game or tournament; team sports use home/away columns; **field sports** (golf, F1) use `event_name` + date. |
| **Stats** (`metric_source` / `stats.xlsx`) | Sports `entity_stat` only | Team sports: player rows with a **TEAM** code. **Field sports:** global rankings without `TEAM` (e.g. world rankings). |
| **Release list** (`releases` / `music.xlsx`, `movies.xlsx`, …) | `content` | One row per album, movie, show, etc. Each entity needs a **release date** (or `premiere_date` / `air_date`) in metadata. |
| **Stock watchlist** (`metric_source` / `top-150-stocks.xlsx`) | `stock` | One row per ticker; columns include **Company Name** and **Ticker**. |
| **`subcategory`** | All templates | Must match the input package when normalized (e.g. `WNBA` ↔ `wnba`, `Music` ↔ `music`, `stocks` ↔ `stocks`). |
| **`openai_api_key`** (in app settings) | Optional | Needed to **compile** natural-language `*_date_rule` columns on upload if you do not ship pre-built `*_date_spec` JSON. **Not used for stock templates** (dates are computed from market calendar + `timeframe`). |

---

## Four question families (pick one per template)

| `question_family` | Vertical | What it generates |
|-------------------|----------|-------------------|
| **`event`** | Sports | One row per scheduled game/event (default). Answers from template text or schedule placeholders. |
| **`entity_stat`** | Sports | One row per game (default); answer choices are player names from the stats file. |
| **`content`** | Entertainment (music, movies, TV, etc.) | One row per release, release pair, or configured static option set. Placeholders filled from the normalized release list. |
| **`stock`** | Stocks | One row per trading day × template × asset (or 4-asset MC set). Dates from U.S. market calendar. |

**Cross-cutting:** set **`generation_scope`** = `season` on sports templates to emit **one row for the whole date window** (championship winner, league stat leader). Default is `event` (per game). See [Season-scoped questions](#season-scoped-questions-generation_scope--season) below.

The sections below cover sports first, then **entertainment (`content`)** and **stocks (`stock`)**.

---

## Sports question types

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

### 3. Season-scoped questions (`generation_scope` = `season`)

Use for **one question per season window** — not tied to a single game. Works across team sports (WNBA, NBA, NFL, MLB, MLS, etc.) when the schedule lists all teams in home/away columns.

| Pattern | `question_family` | `generation_scope` | `answer_options` | Inputs |
|---------|-------------------|--------------------|------------------|--------|
| **Championship / league winner** | `event` | `season` | `{schedule_teams}` (alias `{team_options}`) | Schedule only |
| **Season stat leader** | `entity_stat` | `season` | `{entity_options}` | Schedule + stats |
| **Season yes/no or static MC** | `event` | `season` | `Yes||No` or literal `A||B||C` | Schedule (for dates/context) |

| Field | What to put |
|--------|-------------|
| **`generation_scope`** | **`season`**. Omit or use `event` for per-game templates (default). |
| **`question`** | Season wording with **no** `{home_team}` / `{away_team}` unless you intentionally reference a game. |
| **`answer_options`** | **`{schedule_teams}`** for all teams from the schedule, or **`{entity_options}`** for league-wide player lists. |
| **`stat_column`** / **`top_n_per_team`** | **Season stat leader only.** Use real stat headers (`PTS`, `REB`, `HR`). For `season`, **`top_n_per_team`** = top N players **league-wide** (not per team). |
| **Date columns** | Usually **fixed season dates** (`start_date_rule`, `expiration_date_rule`, `resolution_date_rule`) — not relative to a single tip-off. |

**Export behavior:** one output row per season template. The **`event`** column is a synthetic label like `WNBA 2026 Season` (subcategory + year from the run date window).

**Examples (CSV):**

- Championship: [`samples/wnba_season_championship_one_question.csv`](../samples/wnba_season_championship_one_question.csv)
- Per-game winner (contrast): [`samples/wnba_schedule_game_winner_one_question.csv`](../samples/wnba_schedule_game_winner_one_question.csv)

```csv
id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,generation_scope,start_date_rule,expiration_date_rule,resolution_date_rule
WNBA-007,WNBA,event,Who will win the WNBA Championship?,multiple_choice,{schedule_teams},1,false,season,2026-06-01,2026-06-21,2026-10-21
```

Season stat leader (needs stats; `top_n_per_team` = league-wide N):

```csv
id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,stat_column,top_n_per_team,generation_scope,start_date_rule,expiration_date_rule,resolution_date_rule
WNBA-008,WNBA,entity_stat,Who will finish the season with the highest points per game average?,multiple_choice,{entity_options},1,true,PTS,10,season,2026-06-01,2026-06-21,2026-09-25
```

On wide-table upload, **`generation_scope`** may be inferred as `season` when **`answer_options`** is `{schedule_teams}` or `{team_options}`.

**NOT in scope for this pattern:** MVP nominee lists, division/conference winners (without division data), field sports (golf/F1), standings-dependent props.

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

## Entertainment / content questions (`question_family` = `content`)

Use for **music, movies, television**, and other release-list verticals — not tied to a sports schedule row.

### What you need

| Field | What to put |
|--------|-------------|
| **`question_family`** | `content` |
| **`subcategory`** | Package label, e.g. `Music`, `Movies` (must match `inputs.category_key` / `package_aliases`, e.g. `music` → `Music`). |
| **`requires_entities`** | `false` |
| **`stat_column`** | **Leave empty / omit** |
| **`top_n_per_team`** | **Leave empty / omit** |
| **`question`** | Wording with **bracket placeholders** (preferred) or `{brace}` placeholders. See table below. |
| **`answer_options`** | For **yes/no**: leave blank. For **multiple choice**: literal choices with `||`, or entity placeholders like `[RELEASE_A]||[RELEASE_B]`. |

**Optional but common on entertainment uploads:**

| Column | Purpose |
|--------|---------|
| **`template_type`** | Human label, e.g. `Album Debut Ranking`, `Album Comparison`. |
| **`required_dataset_fields`** | Semicolon-separated fields your input sheet must provide, e.g. `album_or_artist; release_date; topic_import_id`. |
| **`resolution_date_rule`** | Plain English; compiled to `resolution_date_spec` on upload (needs API key). Anchors often use **`release_date`**. |
| **`start_date_rule`**, **`expiration_date_rule`** | Optional; same compile-on-upload behavior as sports. |
| **`generation_strategy`** | Set to `multi_entity_choice` for N-way pick-one templates (or rely on placeholder detection). |
| **`entity_count`** | Override when using multi-entity MC (e.g. 4 for `[MOVIE_A]…[MOVIE_D]`). |

### Placeholders (content)

The generator fills placeholders from the **normalized release list** and settings (`content.static_values` in [`config/settings.yaml`](../config/settings.yaml)).

| Placeholder | Typical use |
|-------------|-------------|
| **`[ALBUM_OR_RELEASE]`** / **`[RELEASE]`** | Single music release (title + artist). |
| **`[MOVIE_TITLE]`** / **`[MOVIE]`** | Single movie title. |
| **`[RELEASE_A]`**, **`[RELEASE_B]`** | Pairwise album comparison (two releases sharing a release date). |
| **`[MOVIE_A]`…`[MOVIE_D]`** | Multi-entity box-office pick-one (same release weekend). |
| **`[YEAR]`**, **`[ARTIST_A]`…`[ARTIST_D]`**, **`[TOUR_CHART_SOURCE]`** | Static templates (fixed option sets from config, not per-row entities). |
| **`[CHART_NAME]`** | Defaults to `Billboard 200` unless overridden in settings. |

Entity metadata keys (e.g. `release_date`, `studio`, `genre`) can also surface as `[STUDIO]`, `[GENRE]`, etc.

### How rows are emitted (content)

| Pattern in template | Behavior |
|----------------------|----------|
| Single-entity markers (`[ALBUM_OR_RELEASE]`, `[MOVIE_TITLE]`, …) | **One output row per release** in the date window. |
| Both `[RELEASE_A]` and `[RELEASE_B]` (or pairwise answer options) | **One row per pair** of releases sharing a release date. |
| `[MOVIE_A]…[MOVIE_N]` / `generation_strategy: multi_entity_choice` | **One row per group** of N releases on the same date. |
| Static markers only (`[YEAR]`, `[ARTIST_A]`, …) without entity markers | **One static row** per template (dates from `content.static_*` settings). |

### Date columns (content)

| Column | Role | Example natural language |
|--------|------|--------------------------|
| **`start_date_rule`** | When the question opens | `7 days before release date` |
| **`expiration_date_rule`** | When entry closes | `release date at midnight` |
| **`resolution_date_rule`** | When the market resolves | `Resolution date should be start_date + 8 days.` |

If date rule columns are **empty**, the app uses legacy heuristics from question/`template_type` text plus optional `content.resolution_dates` / `content.static_*` in settings.

**Example (JSON):** [`tests/fixtures/shipped_templates/music-yn-01.json`](../tests/fixtures/shipped_templates/music-yn-01.json)  
**Example (JSON, pairwise MC):** [`tests/fixtures/shipped_templates/music-mc-01.json`](../tests/fixtures/shipped_templates/music-mc-01.json)

---

## Stock market questions (`question_family` = `stock`)

Stock templates use a **different CSV header layout** from sports/entertainment wide tables. The uploader detects PascalCase client columns automatically.

### Client stock template CSV (Layout A — required for Excel)

**One header row**, then **one row per template**. Required columns:

| Column | Required? | Notes |
|--------|-----------|--------|
| **`Template ID`** | Yes | Unique id, e.g. `stocks_daily_close_higher`. Becomes JSON `id`. |
| **`Question Template`** | Yes | Question text with stock placeholders (see below). |
| **`Answer Type`** | Yes | `yes_no` or `multiple_choice`. |
| **`Template Name`** | Recommended | Human label stored as `template_name`. |
| **`Timeframe`** | Recommended | `Daily`, `Weekly`, `Monthly`, or `Quarterly`. Drives start/expiration/resolution windows. If omitted, inferred from template id (e.g. `stocks_weekly_*`). |
| **`Answer Options`** | Depends | **yes/no:** leave blank. **MC single-asset:** e.g. `Higher||Lower`. **MC four-asset:** must include `{ASSET_1}||{ASSET_2}||{ASSET_3}||{ASSET_4}` (optional `\|\|None`). |
| **`Recommended Priority`** | Optional | Integer priority. |
| **`Notes`** | Optional | Stored as `notes`; for authors only. |

On upload, the app sets **`subcategory`** = `stocks`, **`question_family`** = `stock`, **`requires_entities`** = `false`.

**Do not** use snake_case `template_id` headers for stock bulk uploads unless you intentionally want the generic content parser — stock sheets should use **`Template ID`** (PascalCase).

### Placeholders (stock)

| Placeholder | Filled with |
|-------------|-------------|
| **`{ASSET}`** | Company name from the watchlist (one ticker per row). |
| **`{ASSET_1}`…`{ASSET_4}`** | Four distinct watchlist names for multi-asset MC templates. |
| **`{DATE}`** | Trading date (ISO). |
| **`{MONTH}`**, **`{YEAR}`**, **`{MONTH} {YEAR}`**, **`{QUARTER}`** | Calendar context for weekly/monthly/quarterly wording. |

### Fields to omit on stock templates

| Column | Value |
|--------|--------|
| **`stat_column`**, **`top_n_per_team`** | omit |
| **`start_date_rule`**, **`expiration_date_rule`**, **`resolution_date_rule`** | omit — stripped on save; dates come from [`core/market_calendar.py`](../core/market_calendar.py) + **`timeframe`**. |

### Inputs and settings

- **Watchlist:** `top-150-stocks.xlsx` (or equivalent) under `inputs.files.stocks`.
- **`inputs.category_key`:** `stocks`
- **`topic_import_ids.stocks`:** e.g. `stocks-us-market` (exported on every row).
- **`stocks.questions_per_day`** in settings: target rows per trading day (default 50).

**Example (JSON):** [`tests/fixtures/shipped_templates/stocks_daily_close_higher.json`](../tests/fixtures/shipped_templates/stocks_daily_close_higher.json)  
**Example (JSON, 4-asset MC):** [`tests/fixtures/shipped_templates/stocks_daily_biggest_gainer.json`](../tests/fixtures/shipped_templates/stocks_daily_biggest_gainer.json)

Example CSV header row:

```csv
Template ID,Template Name,Timeframe,Question Template,Answer Type,Answer Options,Recommended Priority,Notes
stocks_daily_close_higher,Daily Close Higher,Daily,Will {ASSET} close higher on {DATE}?,yes_no,,1,Core daily template
stocks_daily_biggest_gainer,Daily Biggest Gainer,Daily,Which of these stocks will gain the most during regular trading hours on {DATE}?,multiple_choice,{ASSET_1}||{ASSET_2}||{ASSET_3}||{ASSET_4}||None,1,Four tickers from watchlist
```

---

## CSV / Excel layouts

**For `.xlsx` / `.xls` and most multi-template CSVs, use Layout A only.**  
Do **not** build Excel with alternating “field name row / value row” pairs (Layout B). That pattern is for small hand-edited CSV files only. If upload fails with *“header/value row pairs (an even number of non-empty rows)”*, the sheet is Layout A but was parsed as Layout B — fix the header row (see below).

### Layout A — Wide table (required for Excel)

**One header row**, then **one row per template** (20 templates ⇒ 21 rows total including the header).

**Sports and entertainment** use snake_case / lowercase headers. **Stocks** use the separate PascalCase layout described above.

**Required header columns** (names are flexible):

- `template_id` **or** `id`
- `question` **or** `question_template` (both work; prefer `question` to match JSON)
- `answer_type`

| Column | Required? | Notes |
|--------|-----------|--------|
| **`template_id`** or **`id`** | Yes | Unique id, e.g. `WNBA-010`, `music-yn-01`. |
| **`subcategory`** | Yes | `WNBA`, `MLB`, `Music`, `Movies`, etc. |
| **`question_template`** or **`question`** | Yes | Question text with placeholders. |
| **`answer_type`** | Yes | `yes_no` or `multiple_choice`. |
| **`answer_options_pattern`** / **`answer_options`** | MC: required pattern; yes_no: optional | Use `||` between choices. |
| **`question_family`** | Recommended | `event`, `entity_stat`, or `content`. If blank and `stat_column` is set → `entity_stat`; otherwise inferred from placeholders/rules. |
| **`requires_entities`** | Recommended | `false` for event/content; `true` for entity_stat. |
| **`stat_column`** | entity_stat only | e.g. `PTS` |
| **`top_n_per_team`** / **`top_n`** | entity_stat only | e.g. `2` |
| **`template_type`** | content only (optional) | e.g. `Album Comparison` |
| **`required_dataset_fields`** | content only (optional) | e.g. `release_a; release_b; chart_week` |
| **`timeframe`** | stock only (in JSON or client CSV) | `Daily`, `Weekly`, `Monthly`, `Quarterly` |
| **`priority`** / **`default_priority`** | Optional | Number or empty. |
| **`start_date_rule`** | Optional | Plain English; compiled on upload if API key set. **Ignored for stock.** |
| **`expiration_date_rule`** | Optional | Plain English. **Ignored for stock.** |
| **`resolution_date_rule`** | Optional | Plain English. **Ignored for stock.** |
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

### Shared columns (all templates)

| Column | Required | Values / notes |
|--------|----------|----------------|
| **`id`** / **`template_id`** | Yes | Unique string. |
| **`subcategory`** | Yes | Package label; must match inputs package (case-insensitive). |
| **`question_family`** | Yes* | `event`, `entity_stat`, `content`, `stock`. *Can infer entity_stat if `stat_column` present; content if entertainment columns present. |
| **`question`** | Yes | Final wording with placeholders filled at generation time. |
| **`answer_type`** | Yes | `yes_no` \| `multiple_choice`. |
| **`answer_options`** | Depends | See below. |
| **`priority`** | Yes in JSON | Integer or empty string in CSV. |
| **`requires_entities`** | Yes in JSON | Boolean: `false` for event/content/stock; `true` for entity_stat. |

### `content` only — entertainment templates

| Column | Value |
|--------|--------|
| **`question_family`** | `content` |
| **`requires_entities`** | `false` |
| **`stat_column`**, **`top_n_per_team`** | omit |
| **`template_type`** | optional human label |
| **`required_dataset_fields`** | optional; documents input columns |
| **`resolution_date_rule`** (and start/expiration rules) | optional; compiled on upload |
| **`question`** | bracket placeholders, e.g. `[ALBUM_OR_RELEASE]` |
| **`answer_options`** | blank for yes/no; `[RELEASE_A]\|\|[RELEASE_B]` for pairwise MC |

### `stock` only — leave these **empty** (or use client CSV columns)

| Column | Value |
|--------|--------|
| **`stat_column`**, **`top_n_per_team`** | omit |
| **`*_date_rule`**, **`*_date_spec`** | omit (stripped on upload) |
| **`timeframe`** | `Daily` \| `Weekly` \| `Monthly` \| `Quarterly` |
| **`template_name`**, **`notes`** | optional metadata |
| **`question`** | `{ASSET}`, `{DATE}`, `{MONTH}`, `{QUARTER}`, etc. |
| **`answer_options`** | blank for yes/no; `{ASSET_1}\|\|…\|\|{ASSET_4}` for 4-way MC |

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

### Date columns (optional; sports `event` / `entity_stat` and `content`)

Three independent timings per output row: **Start Date**, **Expiration Date**, **Resolution Date** (ISO 8601 in export).

| Column | Role | Example natural language (`*_date_rule`) |
|--------|------|----------------------------------------|
| **`start_date_rule`** | When the question opens | Sports: `24 hours after event start`. Content: `7 days before release date`. |
| **`expiration_date_rule`** | When trading/entry closes | Sports: `2 days after event start`. Content: `on release date`. |
| **`resolution_date_rule`** | When the market resolves | Sports: `January 15 of the event calendar year`. Content: `Resolution date should be start_date + 8 days.` |

On upload, non-empty rules are compiled to `*_date_spec` JSON (needs `openai_api_key`) unless you author JSON yourself. **Stock templates ignore these columns** — timing is derived from `timeframe` and the U.S. trading calendar.

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

## Worked example: music album debut (content)

User wants **yes/no** questions for each June release. Upload **music.xlsx** only (no sports schedule).

```csv
template_id,subcategory,template_type,answer_type,question_template,answer_options_pattern,required_dataset_fields,default_priority,resolution_date_rule
music-yn-01,Music,Album Debut Ranking,yes_no,Will [ALBUM_OR_RELEASE] debut on the Billboard 200?,,album_or_artist; release_date; topic_import_id,1,Resolution date should be start_date + 8 days.
```

1. **`question_family`** is inferred as `content` (no `stat_column`, entertainment columns present).
2. **`requires_entities`:** `false`
3. Tell the operator: set **`inputs.category_key`** to `music`, upload **music.xlsx**, enable **`music-yn-01`**, run Generate.

---

## Worked example: daily stock close higher (stock)

User wants a **daily yes/no** per ticker. Upload **top-150-stocks.xlsx** and a **PascalCase** stock template CSV.

```csv
Template ID,Template Name,Timeframe,Question Template,Answer Type,Answer Options,Recommended Priority,Notes
stocks_daily_close_higher,Daily Close Higher,Daily,Will {ASSET} close higher on {DATE} than its previous closing price during regular trading hours?,yes_no,,1,Core daily template
```

1. **`question_family`** is set to `stock` automatically.
2. **Do not set** date rule columns — the app computes start/expiration/resolution from **`Timeframe: Daily`**.
3. Tell the operator: set **`inputs.category_key`** to `stocks`, upload watchlist, enable **`stocks_daily_close_higher`**, set **`stocks.questions_per_day`** if needed, run Generate.

---

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Retrospective or past-tense questions (`Who won?`, `Did X beat Y?`) | Rewrite in future tense: `Who will win?`, `Will X beat Y?` — all questions must be about events that have **not** yet taken place. |
| Excel upload: *even number of non-empty rows* | You used **Layout A** but the app did not recognize the header. Ensure the first row includes **`template_id`** (or `id`), **`question`** (or `question_template`), and **`answer_type`**. One data row per template — not two-row blocks. |
| Stock CSV uploaded as sports wide table | Use PascalCase headers: **`Template ID`**, **`Question Template`**, **`Answer Type`**. |
| `entity_stat` without `stat_column` | Add `stat_column` or change to `event`. |
| `event` with `stat_column` / `top_n_per_team` | Remove those columns; they are ignored and confuse authors. |
| `content` with `stat_column` / sports placeholders | Use `[ALBUM_OR_RELEASE]` / `[MOVIE_TITLE]`, not `{home_team}`. |
| `requires_entities: true` on a winner or content question | Use `false` for `event` and `content`. |
| `{entity_options}` on an `event` template | Use explicit team names or `Yes||No`. |
| Pairwise MC without `[RELEASE_A]` / `[RELEASE_B]` | Both placeholders must appear in question or answer options. |
| 4-asset stock MC missing `{ASSET_1}`…`{ASSET_4}` | All four asset slots required in **`answer_options`**. |
| Date rules on stock templates | Remove them; set **`timeframe`** instead. |
| Bare `Los Angeles` in schedule without team map | Use full team names from schedule (`Los Angeles Sparks`). |
| Championship as `entity_stat` + `{entity_options}` | Use `event` + `{schedule_teams}` + `generation_scope=season`. |
| Season question without `generation_scope=season` | Emits one row **per game** (duplicates). Set `generation_scope=season`. |
| Fake stat columns (`Teams`, `PPG`) | Use real stats headers (`PTS`, `REB`, etc.) from the stats workbook. |
| Mismatched `subcategory` | `WNBA` templates only run when package is `wnba`; `Music` when package is `music`. |

---

## JSON template (single file per template)

Save under `templates/<id>.json`. Same fields as CSV. Example: [`templates/WNBA-010.json`](../templates/WNBA-010.json).

---

## Operator checklist (paste into your reply)

1. Templates use `subcategory` matching the input package (`WNBA`, `Music`, `stocks`, …).
2. **All question text is forward-looking** — future events only; no past-tense or "who won / did X happen" wording.
3. **Sports schedule-only** → `question_family` = `event`, no `stat_column` / `top_n_per_team`.
4. **Sports player props** → `entity_stat` + `stat_column` + `top_n_per_team` + stats file.
5. **Season championship / league winner** → `event` + `{schedule_teams}` + `generation_scope=season` + schedule only.
6. **Season stat leader** → `entity_stat` + `{entity_options}` + `generation_scope=season` + stats file (`top_n_per_team` = league-wide N).
7. **Entertainment** → `question_family` = `content`, release list input, bracket placeholders, optional `resolution_date_rule`.
8. **Stocks** → PascalCase client CSV or JSON with `timeframe`; watchlist input; no date rule columns.
9. Enable template ids in `templates_enabled` in settings (or UI).
10. Upload templates via UI **Templates** step (CSV/XLSX/JSON).

For machine-readable team aliases and package keys, see [`config/team_aliases/README.md`](../config/team_aliases/README.md) and the main [`README.md`](../README.md).
