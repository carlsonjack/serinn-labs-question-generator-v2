| Season leader options look random / not top scorers | Usually wrong `stat_column` or rank column not in `ascending_stat_columns`. Re-read stats headers. |
| `[GOLFER]` / sport-specific entity tokens in question | Use **`[PLAYER]`** only — see [player-prop buckets](#b-player-prop-buckets-player-in-the-question). |
| “Who will win {event_name}?” becomes a season question | Per-tournament MC should omit `generation_scope=season`; use `{event_name}` in the question. Set `generation_scope=event` if unsure. |
| Wrong golfers in MC answer list (worst-ranked names) | Add the rank column (e.g. `FedExCup Rank`) to `ascending_stat_columns` in golf package settings. |
| Template says 35 names but export shows 3 | Set `top_n_per_team` on the template row — explicit template value wins over global UI default. |
| H2H template shows `Golfer_A` / `Golfer_B` instead of real names | Schedule must have **one row per pairing** with both `home_team` and `away_team` filled; each row needs a unique `event_id`. |
| H2H pairings only in stats file | Put matchups in the **schedule** (`home_team` / `away_team` columns), not the stats workbook. |
| MLS assist leader with goals-only stats file | Add an assists workbook/sheet with an assists column, or disable the assist template until that file exists. |
| Golf/F1 season winner with `{schedule_teams}` | Use 008-style: `entity_stat` + `{entity_options}` + rankings/standings stat column. |
| Mismatched `subcategory` | `WNBA` templates only run when package is `wnba`; `GOLF` when package is `golf` (not `PGA`); `Music` when package is `music`. |

---

## JSON template (single file per template)

Save under `templates/<id>.json`. Same fields as CSV. Example: [`templates/WNBA-010.json`](../templates/WNBA-010.json).

---

## Operator checklist (paste into your reply)

1. Templates use `subcategory` matching the input package (`WNBA`, `Music`, `stocks`, …).
2. **All question text is forward-looking** — future events only; no past-tense or "who won / did X happen" wording.
3. **Sports schedule-only** → `question_family` = `event`, no `stat_column` / `top_n_per_team`.
4. **Sports player props** → `entity_stat` + stats file; use **`[PLAYER]`** in the question (never `[GOLFER]`, `[DRIVER]`, etc.); **`stat_column` = exact header from that file**; set `top_n_per_team` on the template row.
5. **Season championship / league winner** → `event` + `{schedule_teams}` + `generation_scope=season` + schedule only.
6. **Season stat leader** → `entity_stat` + `{entity_options}` + `generation_scope=season` + stats file; **`stat_column` copied from stats sheet**; **`top_n_per_team`: `20`** on the template row.
7. **Golf per-tournament MC** → `entity_stat` + `{entity_options}` + `{event_name}` + stats; **`subcategory=GOLF`**; rank columns in `ascending_stat_columns`.
8. **Golf H2H matchups** → `event` + `{home_team}` / `{away_team}` + schedule with **one row per pairing** and unique `event_id`; stats optional.
9. **LLM authoring** → Attach the client’s schedule + stats workbooks (any names) in the same prompt; never guess `stat_column` from question wording alone.
10. **Entertainment** → `question_family` = `content`, release list input, bracket placeholders, optional `resolution_date_rule`.
11. **Stocks** → PascalCase client CSV or JSON with `timeframe`; watchlist input; no date rule columns.
12. Enable template ids in `templates_enabled` in settings (or UI).
13. Upload templates via UI **Templates** step (CSV/XLSX/JSON).

For machine-readable team aliases and package keys, see [`config/team_aliases/README.md`](../config/team_aliases/README.md) and the main [`README.md`](../README.md).
