"""Shared pytest configuration; workbook factories live under ``tests/fixtures/``."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep expensive/provider-backed checks opt-in for normal local and CI runs."""

    run_exhaustive = os.environ.get("RUN_EXHAUSTIVE_TESTS") == "1"
    run_live = (
        os.environ.get("RUN_LIVE_OPENAI_TESTS") == "1"
        and bool(os.environ.get("OPENAI_API_KEY"))
    )
    exhaustive_skip = pytest.mark.skip(
        reason="set RUN_EXHAUSTIVE_TESTS=1 to run exhaustive matrix cases"
    )
    live_skip = pytest.mark.skip(
        reason="set RUN_LIVE_OPENAI_TESTS=1 and OPENAI_API_KEY to run live OpenAI smoke tests"
    )
    for item in items:
        if "exhaustive" in item.keywords and not run_exhaustive:
            item.add_marker(exhaustive_skip)
        if "live_openai" in item.keywords and not run_live:
            item.add_marker(live_skip)
