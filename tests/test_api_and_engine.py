"""Unit and Integration tests for VidyutSetu Validation Engine, Scoring, and APIs."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

import backend.main as main
from backend.main import app
from backend.models.canonical import CanonicalPayload, CanonicalMeterReading
from backend.engine.validator import ValidationEngine
from backend.engine.scorer import ScoringEngine


@pytest.fixture
def client():
    return TestClient(app)


def test_validator_and_scoring():
    payload = CanonicalPayload(
        source_system="test",
        readings=[
            CanonicalMeterReading(
                meter_serial_number="MTR-001",
                timestamp=datetime.now(timezone.utc),
                active_energy_import_kwh=100.0,
                voltage_v=230.0,
                current_a=5.0,
                power_factor=0.95
            )
        ]
    )
    issues, valid, invalid = ValidationEngine.validate_canonical_payload(payload)
    assert valid == 1
    assert invalid == 0

    score = ScoringEngine.calculate_score(1, issues)
    assert score.total_score >= 95.0
    assert score.grade == "A+"


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_root_static_ui_and_service_health(client):
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert client.get("/static/app.js").status_code == 200

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "0.1.0", "db": "ok"}


def test_service_health_reports_database_error(client, monkeypatch):
    class UnavailableEngine:
        def connect(self):
            raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(main, "engine", UnavailableEngine())

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "0.1.0", "db": "error"}


def test_openapi_routes_use_category_tags(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/workbench/execute"]["post"]["tags"] == ["workbench"]
    assert paths["/ml/validate"]["post"]["tags"] == ["ml"]
    assert paths["/api/suites"]["post"]["tags"] == ["suites"]
    assert paths["/api/compare"]["post"]["tags"] == ["compare"]
    assert paths["/api/roundtrip"]["post"]["tags"] == ["roundtrip"]


def test_api_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    assert "total_test_runs" in res.json()


def test_api_synthetic_and_execute(client):
    res_gen = client.post("/api/generate?vendor_id=alpha-hes&meter_count=2&intervals=3")
    assert res_gen.status_code == 200
    payload = res_gen.json()["payload"]

    res_exec = client.post("/api/workbench/execute", data={
        "source_vendor": "alpha-hes",
        "target_vendor": "beta-hes",
        "raw_payload": str(payload).replace("'", '"')
    })
    assert res_exec.status_code == 200
    data = res_exec.json()
    assert data["total_records"] == 6
    assert data["score"]["total_score"] >= 80.0
