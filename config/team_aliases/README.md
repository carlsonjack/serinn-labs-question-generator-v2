# Team aliases

Schedule workbooks often use full club or school names (`Houston Astros`, `Los Angeles Sparks`) while stats workbooks use short codes (`HOU`, `LA`). Each file here maps **aliases → canonical code** for one package.

## File format

```yaml
package_key: nba
package_aliases:
  - NBA
teams:
  - code: LAL
    aliases:
      - Los Angeles Lakers
      - Lakers
      - LAL
```

- `package_key` — normalized via `normalize_template_package` (e.g. `La Liga` → `laliga`).
- `package_aliases` — optional extra keys that share this map.
- `code` — value stored on `PlayerStatRecord.team` and used when joining to stats.
- `aliases` — schedule labels and passthrough codes that resolve to `code`.

The loader rejects duplicate aliases within a file.

## Disambiguation rules

- Map **disambiguated** names (`Los Angeles Dodgers`, `LAFC`, `Los Angeles Lakers`).
- Do **not** map bare city strings when multiple teams share that city (`Los Angeles`, `LA`, `New York` in NBA/NFL/MLS).
- **College (`ncaaf`, `ncaab`):** canonical code is the full school name; avoid shared mascot nicknames (`Tigers`, `Wildcats`). Add only globally unique abbrevs (`USC`, `UConn`, `Miami (FL)`).

## Regenerating

Pro leagues and soccer lists live in [`scripts/generate_team_aliases.py`](../../scripts/generate_team_aliases.py):

```bash
python scripts/generate_team_aliases.py
```

College files use school-name-only rows plus a small disambiguation table in that script.

## Adding a new sport

1. Add `your_league.yaml` under this directory (or extend the generator script).
2. Set `package_key` to the normalized package id used in `inputs.files` / templates.
3. Run tests: `pytest tests/test_team_aliases.py -q`.

No Python registry edit is required — all `*.yaml` files load automatically.
