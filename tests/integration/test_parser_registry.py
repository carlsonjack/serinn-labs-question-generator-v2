"""Integration-lite: normalizer registry contracts."""

from __future__ import annotations

import pytest

from core.parsers.registry import get_category_normalizer, list_registered_categories


@pytest.mark.integration
def test_registered_verticals_include_mlb_and_f1() -> None:
    import core.parsers.service  # noqa: F401

    cats = list_registered_categories()
    assert "mlb" in cats
    assert "f1" in cats
    assert "golf" in cats
    assert "stocks" in cats


@pytest.mark.integration
def test_unknown_package_dual_source_loads_via_mlb_normalizer(tmp_path: Path) -> None:
    """New packages (e.g. MLS) without a dedicated normalizer use MLB-shaped pipeline."""

    from core.parsers.contracts import ValidationSeverity
    from core.parsers.service import load_normalized_bundle
    from tests.fixtures.workbooks import write_mlb_schedule_minimal, write_mlb_stats_minimal

    pkg = "ZZZ_UnknownIntegrationPkg"

    write_mlb_schedule_minimal(tmp_path / "sched.xlsx")
    write_mlb_stats_minimal(tmp_path / "st.xlsx")
    settings: dict = {
        "inputs": {
            "directory": str(tmp_path),
            "category_key": pkg,
            "files": {
                pkg: {
                    "event_source": "sched.xlsx",
                    "metric_source": "st.xlsx",
                }
            },
        },
        "date_filter": {"start": "2020-01-01", "end": "2030-12-31"},
        "parsing": {"persist_profiles": False},
    }
    bundle = load_normalized_bundle(settings, category_key=pkg)
    errors = [i for i in bundle.issues if i.severity == ValidationSeverity.ERROR]
    assert not errors
    assert len(bundle.events) >= 1


@pytest.mark.integration
def test_unknown_package_schedule_only_still_requires_alias_or_normalizer(
    tmp_path: Path,
) -> None:
    from core.parsers.contracts import ValidationSeverity
    from core.parsers.service import load_normalized_bundle
    from tests.fixtures.workbooks import write_mlb_schedule_minimal

    pkg = "ZZZ_UnknownIntegrationPkg"

    write_mlb_schedule_minimal(tmp_path / "sched.xlsx")
    settings: dict = {
        "inputs": {
            "directory": str(tmp_path),
            "category_key": pkg,
            "files": {pkg: {"event_source": "sched.xlsx"}},
        },
        "parsing": {"persist_profiles": False},
    }
    bundle = load_normalized_bundle(settings, category_key=pkg)
    codes = {i.code for i in bundle.issues if i.severity == ValidationSeverity.ERROR}
    assert "unknown_category_normalizer" in codes
