"""Batch A: additive model-version tag and data-quality score on run results."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.db import database
from backend.main import app

client = TestClient(app)


def _delta_payload(meter_id: str, kwh: float = 1200.0) -> dict:
    return {
        "telemetry": [
            {
                "device_uid": meter_id,
                "timestamp": "2026-01-01T00:00:00Z",
                "act_wh": kwh,
                "volt_mv": 230000,
                "curr_ma": 5000,
                "p_fact_pct": 95,
            }
        ]
    }


def _execute(meter_id: str, kwh: float = 1200.0) -> dict:
    response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(_delta_payload(meter_id, kwh)),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_execute_reports_model_version_tag_from_artifact_metadata():
    body = _execute("MTR-METADATA-VERSION")
    health = client.get("/ml/health").json()

    assert body["model_version"]
    assert health["metrics"]["selected_classifier"] in body["model_version"]
    assert health["model_versions"]["fault_classifier"][:12] in body["model_version"]
    assert health["model_versions"]["anomaly_detector"][:8] in body["model_version"]


def test_execute_reports_rule_labelled_data_quality_score():
    body = _execute("MTR-METADATA-QUALITY")
    data_quality = body["data_quality"]

    assert data_quality["source"] == "rule"
    assert 0.0 <= data_quality["score"] <= 100.0
    assert {
        "score",
        "record_validity_pct",
        "error_count",
        "warning_count",
        "issue_density_pct",
    } <= set(data_quality)
    assert data_quality["record_validity_pct"] == 100.0
    assert body["score"]["total_score"] > 0.0


def test_data_quality_score_drops_for_a_payload_with_electrical_errors():
    clean = _execute("MTR-METADATA-CLEAN")
    faulty = _execute("MTR-METADATA-FAULTY", kwh=-1000.0)

    assert faulty["data_quality"]["error_count"] > clean["data_quality"]["error_count"]
    assert faulty["data_quality"]["score"] < clean["data_quality"]["score"]


def test_execute_score_shape_is_unchanged_by_new_fields():
    body = _execute("MTR-METADATA-SHAPE")

    assert set(body["score"]) == {
        "syntactic_score",
        "semantic_score",
        "data_integrity_score",
        "total_score",
        "grade",
        "summary",
    }


def test_run_detail_persists_model_version_and_data_quality():
    executed = _execute("MTR-METADATA-DETAIL")

    detail = client.get(f"/api/test-runs/{executed['run_id']}").json()

    assert detail["model_version"] == executed["model_version"]
    assert detail["data_quality_score"] == executed["data_quality"]["score"]
    assert detail["score"] == executed["score"]


def test_list_runs_exposes_persisted_run_metadata():
    executed = _execute("MTR-METADATA-LIST")

    runs = client.get("/api/test-runs?limit=50").json()
    listed = next(run for run in runs if run["run_id"] == executed["run_id"])

    assert listed["model_version"] == executed["model_version"]
    assert listed["data_quality_score"] == executed["data_quality"]["score"]


def test_init_db_adds_run_metadata_columns_to_an_existing_database(monkeypatch, tmp_path):
    legacy_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{legacy_path}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE test_runs (
                    run_id VARCHAR(64) PRIMARY KEY,
                    execution_time DATETIME,
                    source_vendor VARCHAR(64) NOT NULL,
                    target_vendor VARCHAR(64),
                    total_records INTEGER,
                    valid_records INTEGER,
                    invalid_records INTEGER,
                    syntactic_score FLOAT,
                    semantic_score FLOAT,
                    integrity_score FLOAT,
                    total_score FLOAT,
                    grade VARCHAR(8),
                    summary TEXT,
                    issues_json TEXT,
                    raw_preview TEXT,
                    canonical_preview TEXT,
                    target_preview TEXT,
                    duration_ms FLOAT
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO test_runs (run_id, source_vendor, total_score, grade) "
                "VALUES ('RUN-LEGACY', 'delta-legacy', 88.0, 'A')"
            )
        )
    legacy_engine.dispose()

    engine = create_engine(f"sqlite:///{legacy_path}")
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()

    columns = {column["name"] for column in inspect(engine).get_columns("test_runs")}
    assert {"model_version", "data_quality_score"} <= columns
    indexes = {index["name"] for index in inspect(engine).get_indexes("test_runs")}
    assert "ix_test_runs_execution_time" in indexes
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT run_id, total_score, model_version FROM test_runs")
        ).one()
    assert row.run_id == "RUN-LEGACY"
    assert row.total_score == 88.0
    assert row.model_version is None
    engine.dispose()


def test_init_db_migrates_legacy_suite_runs_foreign_key_without_losing_rows(
    monkeypatch, tmp_path
):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-suite.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE test_suites ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "scenarios_json TEXT NOT NULL DEFAULT '[]', created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE suite_runs ("
                "id INTEGER PRIMARY KEY, suite_id INTEGER NOT NULL, run_at DATETIME, "
                "results_json TEXT NOT NULL DEFAULT '[]', "
                "passed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0)"
            )
        )
        connection.execute(
            text("INSERT INTO test_suites (id, name) VALUES (7, 'legacy suite')")
        )
        connection.execute(
            text(
                "INSERT INTO suite_runs "
                "(id, suite_id, results_json, passed_count, failed_count) "
                "VALUES (9, 7, '[]', 1, 0)"
            )
        )
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()

    foreign_keys = inspect(engine).get_foreign_keys("suite_runs")
    assert any(
        key["constrained_columns"] == ["suite_id"]
        and key["referred_table"] == "test_suites"
        for key in foreign_keys
    )
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, suite_id, results_json, passed_count FROM suite_runs")
        ).one()
    assert tuple(row) == (9, 7, "[]", 1)
    engine.dispose()


def test_init_db_refuses_suite_run_migration_when_orphan_rows_exist(
    monkeypatch, tmp_path
):
    engine = create_engine(f"sqlite:///{tmp_path / 'orphan-suite.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE test_suites ("
                "id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
                "scenarios_json TEXT NOT NULL DEFAULT '[]', created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE suite_runs ("
                "id INTEGER PRIMARY KEY, suite_id INTEGER NOT NULL, run_at DATETIME, "
                "results_json TEXT NOT NULL DEFAULT '[]', "
                "passed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO suite_runs "
                "(id, suite_id, results_json, passed_count, failed_count) "
                "VALUES (9, 404, '[]', 0, 0)"
            )
        )
    monkeypatch.setattr(database, "engine", engine)

    with pytest.raises(RuntimeError, match="orphaned suite runs"):
        database.init_db()

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, suite_id FROM suite_runs")
        ).one()
    assert tuple(row) == (9, 404)
    assert "suite_runs_migrating" not in inspect(engine).get_table_names()
    engine.dispose()


def test_init_db_is_idempotent_when_columns_already_exist(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()
    database.init_db()

    columns = [column["name"] for column in inspect(engine).get_columns("test_runs")]
    assert columns.count("model_version") == 1
    assert columns.count("data_quality_score") == 1
    engine.dispose()
