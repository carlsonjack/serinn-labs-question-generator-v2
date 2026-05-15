"""Tests for AI-backed home-team timezone inference (cache + OpenAI mock)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.event_timezone_infer import infer_team_timezones_from_names


@pytest.fixture(autouse=True)
def clear_timezone_cache(monkeypatch, tmp_path):
    """Use an isolated cache file so tests do not read the user's disk cache."""

    cache = tmp_path / "tz_cache.json"
    monkeypatch.setattr("core.event_timezone_infer.CACHE_PATH", cache)
    yield
    if cache.is_file():
        cache.unlink()


def test_infer_team_timezones_skips_when_no_api_key() -> None:
    out = infer_team_timezones_from_names(["LA Galaxy"], {"openai_api_key": ""})
    assert out == {}


def test_infer_team_timezones_with_mock_client_writes_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "tz.json"
    monkeypatch.setattr("core.event_timezone_infer.CACHE_PATH", cache)

    client = MagicMock()
    client.chat.completions.create = MagicMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps(
                            {
                                "mappings": {
                                    "LA Galaxy": "America/Los_Angeles",
                                    "Chicago Fire": "America/Chicago",
                                }
                            }
                        ),
                        refusal=None,
                    )
                )
            ]
        )
    )
    settings = {"openai_api_key": "sk-test", "model": "gpt-test"}
    out = infer_team_timezones_from_names(
        ["LA Galaxy", "Chicago Fire"],
        settings,
        client=client,
    )
    assert out["LA Galaxy"] == "America/Los_Angeles"
    assert out["Chicago Fire"] == "America/Chicago"
    assert cache.is_file()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["LA Galaxy"] == "America/Los_Angeles"
    client.chat.completions.create.assert_called_once()

    # Second call uses cache only
    client.chat.completions.create.reset_mock()
    out2 = infer_team_timezones_from_names(["LA Galaxy"], settings, client=client)
    assert out2 == {"LA Galaxy": "America/Los_Angeles"}
    client.chat.completions.create.assert_not_called()
