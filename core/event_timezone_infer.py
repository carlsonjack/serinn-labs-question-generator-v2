"""Infer IANA timezones for sports home teams when YAML ``event_datetime.timezone`` is unset."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from openai import OpenAI
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def _cache_path() -> Path:
    from core.data_layout import bootstrap_if_needed, get_writable_root, uses_writable_data_tree

    bootstrap_if_needed()
    base = get_writable_root() if uses_writable_data_tree() else _ROOT
    return base / "config" / "event_team_timezone_cache.json"


_CHUNK = 40


def _load_cache() -> dict[str, str]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            out[k.strip()] = v.strip()
    return out


def _save_cache(cache: dict[str, str]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _load_cache()
    merged.update(cache)
    sorted_keys = sorted(merged.keys(), key=str.lower)
    ordered = {k: merged[k] for k in sorted_keys}
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def _validate_iana(name: str) -> bool:
    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


def infer_team_timezones_from_names(
    team_names: Sequence[str],
    settings: Mapping[str, Any],
    *,
    client: Optional[OpenAI] = None,
) -> dict[str, str]:
    """Return mapping team_display_name -> IANA zone. Uses disk cache + OpenAI for unknowns."""

    names = [str(n).strip() for n in team_names if str(n).strip()]
    if not names:
        return {}
    cache = _load_cache()
    out: dict[str, str] = {n: cache[n] for n in names if n in cache}
    missing = [n for n in names if n not in out]
    if not missing:
        return out
    api_key = str(settings.get("openai_api_key") or "").strip()
    if not api_key:
        logger.info(
            "Skipping AI timezone inference for %d team(s): openai_api_key not set",
            len(missing),
        )
        return out
    model = str(settings.get("model") or "gpt-4.1")
    openai_client = client or OpenAI(api_key=api_key)
    new_entries: dict[str, str] = {}
    for i in range(0, len(missing), _CHUNK):
        chunk = missing[i : i + _CHUNK]
        batch = _fetch_openai_team_timezones(chunk, openai_client, model)
        for team, tz in batch.items():
            if team in chunk and _validate_iana(tz):
                new_entries[team] = tz
            elif team in chunk:
                logger.warning("AI returned invalid IANA timezone %r for team %r", tz, team)
    if new_entries:
        cache.update(new_entries)
        _save_cache(cache)
        out.update({n: cache[n] for n in names if n in cache})
    return out


def _fetch_openai_team_timezones(
    teams: list[str], openai_client: OpenAI, model: str
) -> dict[str, str]:
    """Ask the model for a JSON object mapping each team name to an IANA timezone."""

    payload = json.dumps({"teams": teams}, indent=2)
    system = (
        "You map professional sports team display names to IANA timezone identifiers "
        "(e.g. America/Los_Angeles) for the team's primary home market. "
        "Respond with JSON only: {\"mappings\": {\"Team Name\": \"Area/City\", ...}} "
        "Include every team from the user list as a key. Use only valid IANA names."
    )
    resp = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": payload},
        ],
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in mappings.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k.strip()] = v.strip()
    return out
