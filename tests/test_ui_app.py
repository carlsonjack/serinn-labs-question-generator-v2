"""Flask UI routes (Epic 8)."""

from __future__ import annotations

import io
import json
import time
from unittest.mock import patch

import pytest

from core.parsers.contracts import ContentEntity, NormalizedBundle
from core.pipeline import PipelineResult
from core.template_config.schema import QuestionTemplate
from tests.fixtures.workbooks import write_stock_list_minimal
import ui.app as ui_app
from ui.app import create_app


@pytest.fixture(autouse=True)
def reset_ui_jobs():
    with ui_app._LOCK:
        ui_app._JOBS.clear()
        ui_app._ACTIVE_RUN = False
    yield
    with ui_app._LOCK:
        ui_app._JOBS.clear()
        ui_app._ACTIVE_RUN = False


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_save_input_category_unknown_package(client):
    rv = client.post("/api/input-category", json={"category_key": "not_a_pkg"})
    assert rv.status_code == 400
    assert "Unknown" in rv.get_json()["error"]


def test_api_save_input_category_persists_canonical_key(client, tmp_path, monkeypatch):
    cfg = tmp_path / "settings.yaml"
    monkeypatch.setattr("core.config._SETTINGS_PATH_OVERRIDE", cfg)
    monkeypatch.setattr("core.config._SETTINGS_LOCAL_PATH_OVERRIDE", tmp_path / "nope.local.yaml")
    cfg.write_text(
        "inputs:\n"
        "  directory: inputs\n"
        "  category_key: mlb\n"
        "  files:\n"
        "    MLS:\n"
        "      event_source: schedule.xlsx\n"
        "    mlb:\n"
        "      event_source: a.xlsx\n",
        encoding="utf-8",
    )
    rv = client.post("/api/input-category", json={"category_key": "mls"})
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True, "category_key": "MLS"}
    from core.config import load_settings_disk_only

    data = load_settings_disk_only()
    assert data["inputs"]["category_key"] == "MLS"


def test_load_topic_import_ids_catalog_normalizes_entries(tmp_path):
    catalog = tmp_path / "topic_import_ids_catalog.json"
    catalog.write_text(
        json.dumps(
            [
                "mlb-mlb-season-2026",
                {"id": " nba-nba-season-2025-2026 ", "label": " NBA Season "},
                {"id": "", "label": "ignored"},
                {"label": "missing id"},
            ]
        ),
        encoding="utf-8",
    )

    assert ui_app.load_topic_import_ids_catalog(catalog) == [
        {"id": "mlb-mlb-season-2026", "label": ""},
        {"id": "nba-nba-season-2025-2026", "label": "NBA Season"},
    ]


def test_load_topic_import_ids_catalog_missing_file_returns_empty(tmp_path):
    assert ui_app.load_topic_import_ids_catalog(tmp_path / "missing.json") == []


def test_topic_import_ids_catalog_file_is_sorted_and_nonempty():
    catalog = ui_app.load_topic_import_ids_catalog()
    ids = [entry["id"] for entry in catalog]

    assert ids
    assert ids == sorted(ids)
    assert all(entry["id"] for entry in catalog)


def test_index_renders_topic_import_id_combobox(client, tmp_path, monkeypatch):
    settings = {
        "topic_import_id": "mlb-mlb-season-2026",
        "subcategory": "MLB",
        "top_n_per_team": 3,
        "date_filter": {"start": "2026-01-01", "end": "2026-02-01"},
        "templates_enabled": {},
        "inputs": {
            "directory": "inputs",
            "category_key": "mlb",
            "files": {"mlb": {}},
        },
    }

    monkeypatch.setattr("ui.app.load_settings", lambda: settings)
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr(
        "ui.app.load_topic_import_ids_catalog",
        lambda: [{"id": "mlb-mlb-season-2026", "label": "MLB | MLB | MLB Season 2026"}],
    )

    rv = client.get("/")

    assert rv.status_code == 200
    assert b'id="topic_import_id"' in rv.data
    assert b'role="combobox"' in rv.data
    assert b"mlb-mlb-season-2026" in rv.data
    assert b"btn-save-topic-import-catalog" in rv.data


def test_api_append_topic_import_id_catalog(client, tmp_path, monkeypatch):
    cat = tmp_path / "topic_import_ids_catalog.json"
    cat.write_text(json.dumps([{"id": "existing-id", "label": ""}]), encoding="utf-8")
    monkeypatch.setattr("core.topic_import_catalog._CATALOG_PATH_OVERRIDE", cat)

    bad = client.post("/api/topic-import-ids/catalog", json={})
    assert bad.status_code == 400

    dup = client.post("/api/topic-import-ids/catalog", json={"topic_import_id": "EXISTING-ID"})
    assert dup.status_code == 200
    assert dup.get_json()["already_exists"] is True

    ok = client.post("/api/topic-import-ids/catalog", json={"topic_import_id": "new-custom-id"})
    assert ok.status_code == 200
    j = ok.get_json()
    assert j["added"] is True
    data = json.loads(cat.read_text(encoding="utf-8"))
    assert any(e["id"] == "new-custom-id" for e in data)


def test_download_rejects_traversal(client):
    rv = client.get("/download/../secrets")
    assert rv.status_code == 404


def test_download_requires_file_under_outputs(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.DEFAULT_OUTPUT_DIR", tmp_path)
    safe = tmp_path / "out.csv"
    safe.write_text("a,b\n", encoding="utf-8")

    rv = client.get("/download/out.csv")
    assert rv.status_code == 200
    assert b"a,b" in rv.data


def test_download_missing_file_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.DEFAULT_OUTPUT_DIR", tmp_path)
    rv = client.get("/download/nope.csv")
    assert rv.status_code == 404


def test_run_returns_409_when_job_active(client):
    def slow_run(*_a, **_k):
        time.sleep(0.4)
        return PipelineResult(success=True)

    fake_settings = {
        "openai_api_key": "sk-test",
        "topic_import_id": "x",
        "subcategory": "MLB",
        "date_filter": {"start": "2026-05-15", "end": "2026-06-01"},
        "templates_enabled": {},
        "inputs": {"directory": "inputs", "files": {"mlb": {}}},
    }

    with (
        patch("ui.app.save_settings_yaml"),
        patch("ui.app.load_settings", return_value=fake_settings),
        patch("ui.app.run_pipeline", side_effect=slow_run),
    ):
        r1 = client.post(
            "/run",
            json={
                "topic_import_id": "x",
                "subcategory": "MLB",
                "top_n_per_team": 2,
                "date_start": "2026-05-15",
                "date_end": "2026-06-01",
                "templates_enabled": {},
            },
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/run",
            json={
                "topic_import_id": "x",
                "subcategory": "MLB",
                "top_n_per_team": 2,
                "date_start": "2026-05-15",
                "date_end": "2026-06-01",
                "templates_enabled": {},
            },
        )
        assert r2.status_code == 409
    time.sleep(0.5)


def test_run_status_unknown_job(client):
    rv = client.get("/run/status/not-a-real-id")
    assert rv.status_code == 404


def test_upload_requires_xlsx(client):
    rv = client.post("/upload", data={})
    assert rv.status_code == 400


def test_upload_applies_inferred_date_range_to_settings(client, tmp_path, monkeypatch):
    import pandas as pd

    import ui.app as ui_app

    root = tmp_path / "root"
    (root / "inputs").mkdir(parents=True)
    monkeypatch.setattr(ui_app, "_inputs_directory", lambda _s: root / "inputs")

    writes: list[dict] = []

    def spy_save(updates: dict) -> None:
        writes.append(dict(updates))

    monkeypatch.setattr(ui_app, "save_settings_yaml", spy_save)
    monkeypatch.setattr(
        ui_app,
        "infer_date_range_from_excel_paths",
        lambda _paths: ("2026-06-01", "2026-06-30"),
    )
    monkeypatch.setattr(
        ui_app,
        "load_settings",
        lambda: {
            "inputs": {
                "directory": "inputs",
                "category_key": "p",
                "files": {"p": {"event_source": "game.xlsx"}},
            },
        },
    )

    bio = io.BytesIO()
    pd.DataFrame([{"Date": "2026-05-01"}]).to_excel(bio, index=False)
    bio.seek(0)

    rv = client.post(
        "/upload",
        data={"category_key": "p", "event_source": (bio, "ignored.xlsx")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["date_filter_auto"]["applied"] is True
    assert data["date_filter_auto"]["start"] == "2026-06-01"
    assert data["date_filter_auto"]["end"] == "2026-06-30"
    assert writes == [{"date_filter": {"start": "2026-06-01", "end": "2026-06-30"}}]
    assert (root / "inputs" / "game.xlsx").is_file()


def test_upload_templates_writes_json(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    tpl = {
        "id": "ui_test_tpl",
        "subcategory": "MLB",
        "question_family": "event",
        "question": "Smoke test question?",
        "answer_type": "yes_no",
        "answer_options": "Yes||No",
        "priority": "",
        "requires_entities": False,
    }
    body = json.dumps(tpl)
    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(body.encode("utf-8")), "upload.json")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert any(x["id"] == "ui_test_tpl" for x in data["saved"])
    out = tmp_path / "ui_test_tpl.json"
    assert out.is_file()
    assert "Smoke test" in out.read_text(encoding="utf-8")


def test_upload_templates_writes_multiple_templates_from_csv(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    body = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "csv_tpl_one,MLB,event,First?,yes_no,Yes||No,,false\n"
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities,stat_column,top_n_per_team\n"
        "csv_tpl_two,MLB,entity_stat,Second?,multiple_choice,{entity_options},,true,HR,3\n"
    )
    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(body.encode("utf-8")), "upload.csv")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert [x["id"] for x in data["saved"]] == ["csv_tpl_one", "csv_tpl_two"]
    assert (tmp_path / "csv_tpl_one.json").is_file()
    assert (tmp_path / "csv_tpl_two.json").is_file()


def test_upload_templates_normalizes_movie_placeholders(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)
    monkeypatch.setattr(
        "ui.app.load_settings",
        lambda: {
            "openai_api_key": "",
            "inputs": {"category_key": "movies", "files": {"movies": {}}},
        },
    )
    monkeypatch.setattr(
        "ui.app.load_normalized_bundle",
        lambda _settings, category_key: NormalizedBundle(
            entities=[
                ContentEntity(
                    entity_id="alpha",
                    display_name="Alpha",
                    metadata={"title": "Alpha", "release_date": "2026-05-15"},
                ),
                ContentEntity(
                    entity_id="bravo",
                    display_name="Bravo",
                    metadata={"title": "Bravo", "release_date": "2026-05-15"},
                ),
            ]
        ),
    )
    tpl = {
        "id": "movie_upload_tpl",
        "subcategory": "Movies",
        "question_family": "content",
        "question": "Which movie wins?",
        "answer_type": "multiple_choice",
        "answer_options": "[MOVIE_A]||[MOVIE_B]",
        "priority": 1,
        "requires_entities": False,
    }

    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(json.dumps(tpl).encode("utf-8")), "upload.json")},
        content_type="multipart/form-data",
    )

    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert "Mapped [MOVIE_A] to [ENTITY_A]." in [w["warning"] for w in data["warnings"]]
    saved = json.loads((tmp_path / "movie_upload_tpl.json").read_text(encoding="utf-8"))
    assert saved["answer_options"] == "[ENTITY_A]||[ENTITY_B]"
    assert saved["generation_strategy"] == "multi_entity_choice"


def _minimal_template_json(tpl_id: str, question: str = "Q?") -> str:
    return json.dumps(
        {
            "id": tpl_id,
            "subcategory": "MLB",
            "question_family": "event",
            "question": question,
            "answer_type": "yes_no",
            "answer_options": "Yes||No",
            "priority": "",
            "requires_entities": False,
        }
    )


def test_upload_templates_409_when_id_exists_elsewhere(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    (tmp_path / "legacy_name.json").write_text(
        _minimal_template_json("disk_dup_id"), encoding="utf-8"
    )

    body = _minimal_template_json("disk_dup_id")
    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(body.encode("utf-8")), "upload.json")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 409
    j = rv.get_json()
    assert j.get("conflict") is True
    assert any(c["template_id"] == "disk_dup_id" for c in j["conflicts"])
    assert (tmp_path / "legacy_name.json").is_file()
    assert not (tmp_path / "disk_dup_id.json").is_file()


def test_upload_templates_replace_existing_removes_legacy_duplicate(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    legacy = tmp_path / "legacy_name.json"
    legacy.write_text(_minimal_template_json("disk_dup_id"), encoding="utf-8")

    body = _minimal_template_json("disk_dup_id", question="Updated Q?")
    rv = client.post(
        "/upload/templates",
        data={
            "file": (io.BytesIO(body.encode("utf-8")), "upload.json"),
            "replace_existing": "1",
        },
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    j = rv.get_json()
    assert j.get("replaced_duplicates") is True
    canonical = tmp_path / "disk_dup_id.json"
    assert canonical.is_file()
    assert "Updated Q?" in canonical.read_text(encoding="utf-8")
    assert not legacy.is_file()


def test_upload_templates_same_canonical_file_rewrites_without_409(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    (tmp_path / "same_id.json").write_text(
        _minimal_template_json("same_id", question="Old?"), encoding="utf-8"
    )
    body = _minimal_template_json("same_id", question="New?")
    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(body.encode("utf-8")), "reupload.json")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    assert "New?" in (tmp_path / "same_id.json").read_text(encoding="utf-8")


def test_upload_templates_rejects_duplicate_ids_in_csv(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: {"templates_enabled": {}})
    monkeypatch.setattr("ui.app.save_settings_yaml", lambda _u: None)

    body = (
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "dup_tpl,MLB,event,First?,yes_no,Yes||No,,false\n"
        "id,subcategory,question_family,question,answer_type,answer_options,priority,requires_entities\n"
        "dup_tpl,MLB,event,Second?,yes_no,Yes||No,,false\n"
    )
    rv = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(body.encode("utf-8")), "upload.csv")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert [x["id"] for x in data["saved"]] == ["dup_tpl"]
    assert "Duplicate template id in upload" in data["errors"][0]["error"]


def test_api_input_slots_returns_package_filtered_templates(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ui.app.load_settings",
        lambda: {
            "subcategory": "MLB",
            "templates_enabled": {"mlb_a": True, "ent_a": False},
            "inputs": {
                "directory": "inputs",
                "category_key": "mlb",
                "files": {
                    "mlb": {"event_source": "schedule.xlsx"},
                    "entertainment": {"event_source": "ent.xlsx"},
                },
            },
        },
    )
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: tmp_path)
    monkeypatch.setattr(
        "ui.app.load_template_dir",
        lambda _p: {
            "mlb_a": QuestionTemplate(
                id="mlb_a",
                subcategory="MLB",
                question_family="event",
                question="MLB question?",
                answer_type="yes_no",
                answer_options="Yes||No",
                priority="",
                requires_entities=False,
            ),
            "ent_a": QuestionTemplate(
                id="ent_a",
                subcategory="Entertainment",
                question_family="event",
                question="Entertainment question?",
                answer_type="yes_no",
                answer_options="Yes||No",
                priority="",
                requires_entities=False,
            ),
        },
    )

    rv = client.get("/api/input-slots?category=mlb")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["category_key"] == "mlb"
    assert [x["id"] for x in data["template_meta"]] == ["mlb_a"]
    assert data["template_subcategory"] == "MLB"


def test_api_normalizer_analyze_stocks_returns_entity_preview(client, tmp_path, monkeypatch):
    inputs_dir = tmp_path / "inputs"
    write_stock_list_minimal(inputs_dir / "stocks.csv")
    settings = {
        "openai_api_key": "sk-test",
        "inputs": {
            "directory": str(inputs_dir),
            "category_key": "stocks",
            "files": {"stocks": {"metric_source": "stocks.csv"}},
            "file_roles": {"stocks": {"metric_source": "entity_source"}},
        },
    }

    monkeypatch.setattr("ui.app.load_settings", lambda: settings)

    rv = client.post(
        "/api/normalizer/analyze",
        json={"category_key": "stocks", "use_ai": True},
    )

    assert rv.status_code == 200
    data = rv.get_json()
    assert data["used_ai"] is False
    assert data["spec"]["sources"]["metric_source"]["source_role"] == "entity_source"
    assert data["preview"]["event_count"] == 0
    assert data["preview"]["player_stat_count"] == 0
    assert data["preview"]["entity_count"] == 6
    assert data["preview"]["entities"][0]["display_name"] == "Apple Inc. (AAPL)"


def test_ui_handoff_package_alias_upload_and_run(client, tmp_path, monkeypatch):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    settings = {
        "openai_api_key": "sk-test",
        "topic_import_id": "default",
        "topic_import_ids": {"formula_one": "f1-race-winner"},
        "subcategory": "F1",
        "date_filter": {"start": "2026-01-01", "end": "2026-12-31"},
        "templates_enabled": {},
        "inputs": {
            "directory": str(tmp_path / "inputs"),
            "category_key": "formula_one",
            "files": {"formula_one": {"schedule": "f1_schedule.xlsx"}},
            "file_roles": {"formula_one": {"schedule": "event_source"}},
            "package_aliases": {"formula_one": "F1"},
        },
    }

    def save_updates(updates):
        updates = dict(updates)
        inputs_files = updates.pop("_inputs_files", None)
        if inputs_files is not None:
            settings.setdefault("inputs", {})["files"] = inputs_files
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value

    monkeypatch.setattr("ui.app.load_settings", lambda: settings)
    monkeypatch.setattr("ui.app.load_settings_disk_only", lambda: settings)
    monkeypatch.setattr("ui.app.save_settings_yaml", save_updates)
    monkeypatch.setattr("ui.app.resolve_templates_directory", lambda _s: template_dir)
    monkeypatch.setattr("ui.app.run_pipeline", lambda *_a, **_k: PipelineResult(success=True))

    before = client.get("/api/input-slots?category=formula_one")
    assert before.status_code == 200
    assert before.get_json()["template_meta"] == []

    tpl = {
        "id": "f1_upload_alias_tpl",
        "subcategory": "F1",
        "question_family": "event",
        "question": "Will {home_team} win the race?",
        "answer_type": "yes_no",
        "answer_options": "Yes||No",
        "priority": "",
        "requires_entities": False,
    }
    uploaded = client.post(
        "/upload/templates",
        data={"file": (io.BytesIO(json.dumps(tpl).encode("utf-8")), "f1_tpl.json")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    assert uploaded.get_json()["saved"][0]["id"] == "f1_upload_alias_tpl"

    after = client.get("/api/input-slots?category=formula_one")
    assert after.status_code == 200
    meta = after.get_json()["template_meta"]
    assert [item["id"] for item in meta] == ["f1_upload_alias_tpl"]
    assert after.get_json()["template_subcategory"] == "F1"

    run = client.post(
        "/run",
        json={
            "input_category_key": "formula_one",
            "templates_enabled": {"f1_upload_alias_tpl": True},
        },
    )
    assert run.status_code == 200
    job_id = run.get_json()["job_id"]
    for _ in range(20):
        status = client.get(f"/run/status/{job_id}").get_json()
        if status["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert status["state"] == "succeeded"


def test_api_save_inputs_files(client, tmp_path, monkeypatch):
    cfg = tmp_path / "settings.yaml"
    monkeypatch.setattr("core.config._SETTINGS_PATH_OVERRIDE", cfg)
    monkeypatch.setattr("core.config._SETTINGS_LOCAL_PATH_OVERRIDE", tmp_path / "nope.local.yaml")

    cfg.write_text(
        "inputs:\n"
        "  directory: inputs\n"
        "  category_key: mlb\n"
        "  files:\n"
        "    mlb:\n"
        "      event_source: a.xlsx\n",
        encoding="utf-8",
    )
    rv = client.post(
        "/api/inputs-files",
        json={
            "files": {
                "mlb": {
                    "event_source": "schedule.xlsx",
                    "metric_source": "stats.xlsx",
                }
            }
        },
    )
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["ok"] is True
    assert j["category_key"] == "mlb"
    from core.config import load_settings_disk_only

    data = load_settings_disk_only()
    assert data["inputs"]["files"]["mlb"]["metric_source"] == "stats.xlsx"


def test_api_save_inputs_files_rejects_empty(client):
    rv = client.post("/api/inputs-files", json={"files": {}})
    assert rv.status_code == 400


def test_save_settings_yaml_roundtrip(tmp_path, monkeypatch):
    from core.config import load_settings_disk_only, save_settings_yaml

    cfg = tmp_path / "settings.yaml"
    monkeypatch.setattr("core.config._SETTINGS_PATH_OVERRIDE", cfg)
    monkeypatch.setattr("core.config._SETTINGS_LOCAL_PATH_OVERRIDE", tmp_path / "nope.yaml")

    cfg.write_text(
        "topic_import_id: \"x\"\ndate_filter:\n  start: \"2026-01-01\"\n  end: \"2026-02-01\"\n",
        encoding="utf-8",
    )
    save_settings_yaml({"subcategory": "MLB", "top_n_per_team": 4})
    data = load_settings_disk_only()
    assert data["subcategory"] == "MLB"
    assert data["top_n_per_team"] == 4
    assert data["date_filter"]["start"] == "2026-01-01"
