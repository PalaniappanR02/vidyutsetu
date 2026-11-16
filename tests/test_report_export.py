"""Batch B: exportable HTML conformance report built from a persisted run."""

import json

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _execute(raw_payload: dict) -> dict:
    response = client.post(
        "/api/workbench/execute",
        data={"source_vendor": "delta-legacy", "raw_payload": json.dumps(raw_payload)},
    )
    assert response.status_code == 200
    return response.json()


def _faulty_payload(device_uid: str = "MTR-REPORT") -> dict:
    return {
        "telemetry": [
            {
                "device_uid": device_uid,
                "timestamp": "2026-01-01T00:00:00Z",
                "act_wh": -1000,
                "volt_mv": 230000,
            }
        ]
    }


def test_report_export_renders_a_real_run():
    run = _execute(_faulty_payload())

    response = client.get(f"/api/test-runs/{run['run_id']}/report.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert run["run_id"] in body
    assert str(run["score"]["total_score"]) in body
    assert run["model_version"] in body
    assert "NEGATIVE_ACTIVE_ENERGY" in body
    assert "synthetic" in body.lower()
    assert "does not certify compliance" in body.lower()
    assert "data-quality" in body.lower() or "data quality" in body.lower()


def test_report_export_404_for_unknown_run():
    response = client.get("/api/test-runs/RUN-DOES-NOT-EXIST/report.html")

    assert response.status_code == 404


def test_report_export_escapes_payload_content():
    run = _execute(_faulty_payload("<script>alert(1)</script>"))

    body = client.get(f"/api/test-runs/{run['run_id']}/report.html").text

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
