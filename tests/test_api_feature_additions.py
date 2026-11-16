import json
import uuid

from fastapi.testclient import TestClient

from backend.api import ml_routes
from backend.db import database
from backend.db.database import DBMeterHistory
from backend.main import app


client = TestClient(app)


def _delta_payload(
    meter_id: str,
    kwh: float = 1200.0,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> dict:
    return {
        "telemetry": [
            {
                "device_uid": meter_id,
                "timestamp": timestamp,
                "act_wh": kwh,
                "volt_mv": 230000,
                "curr_ma": 5000,
                "p_fact_pct": 95,
            }
        ]
    }


def _execute_delta(meter_id: str, kwh: float = 1200.0) -> dict:
    response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(_delta_payload(meter_id, kwh)),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_workbench_adds_five_stages_without_changing_score_shape():
    response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(_delta_payload("MTR-STAGES")),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [stage["name"] for stage in body["stages"]] == [
        "parse",
        "syntactic",
        "semantic mapping",
        "physical sanity",
        "ML screening",
    ]
    assert all(
        {"status", "duration_ms", "diagnostics", "root_cause", "suggested_action"}
        <= set(stage)
        for stage in body["stages"]
    )
    assert set(body["score"]) == {
        "syntactic_score",
        "semantic_score",
        "data_integrity_score",
        "total_score",
        "grade",
        "summary",
    }


def test_missing_delta_energy_is_a_semantic_mapping_diagnostic():
    payload = _delta_payload("MTR-SEMANTIC")
    del payload["telemetry"][0]["act_wh"]

    response = client.post(
        "/api/workbench/execute",
        data={"source_vendor": "delta-legacy", "raw_payload": json.dumps(payload)},
    )

    assert response.status_code == 200
    semantic_stage = next(
        stage for stage in response.json()["stages"] if stage["name"] == "semantic mapping"
    )
    assert semantic_stage["status"] == "fail"
    assert any(issue["code"] == "MISSING_ACT_WH" for issue in semantic_stage["diagnostics"])


def test_compare_reports_new_failures_and_score_deltas():
    baseline = _execute_delta("MTR-COMPARE-BASE")
    candidate_payload = _delta_payload(
        "MTR-COMPARE-CANDIDATE",
        -1000.0,
        timestamp="2026-01-01T00:00:00",
    )
    candidate_response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(candidate_payload),
        },
    )
    assert candidate_response.status_code == 200
    candidate = candidate_response.json()

    response = client.post(
        "/api/compare",
        json={
            "baseline_run_id": baseline["run_id"],
            "candidate_run_id": candidate["run_id"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert any(
        issue["code"] == "NEGATIVE_ACTIVE_ENERGY"
        for issue in body["newly_introduced"]
    )
    assert any(
        issue["code"] == "NAIVE_TIMESTAMP"
        for issue in body["newly_introduced"]
    )
    assert body["score_deltas"]["total_score"] < 0


def test_roundtrip_reports_field_level_differences():
    payload = {
        "system_id": "alpha-hes",
        "meter_data": [
            {
                "meter_number": "MTR-ROUNDTRIP",
                "clock": "2026-01-01T00:00:00Z",
                "registers": {
                    "1.0.1.8.0.255": {"value": 12.5, "scaler": 0},
                    "1.0.9.8.0.255": {"value": 13.0, "scaler": 0},
                    "1.0.12.7.0.255": {"value": 230, "scaler": 0},
                },
            }
        ],
    }

    response = client.post(
        "/api/roundtrip",
        json={"vendor_a": "alpha-hes", "vendor_b": "delta-legacy", "payload": payload},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["converted_payload"]["telemetry"]
    assert any(item["field"] == "apparent_energy_kvah" for item in body["field_differences"])


def test_suite_create_list_and_run_reuses_workbench_execution():
    response = client.post(
        "/api/suites",
        json={
            "name": f"API suite {uuid.uuid4().hex}",
            "scenarios": [
                {
                    "source_vendor": "delta-legacy",
                    "payload": _delta_payload("MTR-SUITE"),
                },
                {
                    "source_vendor": "delta-legacy",
                    "payload": _delta_payload("MTR-SUITE-FAIL", -1000.0),
                },
            ],
        },
    )

    assert response.status_code == 200
    suite = response.json()
    assert suite["scenarios"]
    assert any(item["id"] == suite["id"] for item in client.get("/api/suites").json())

    run_response = client.post(f"/api/suites/{suite['id']}/run")

    assert run_response.status_code == 200
    run = run_response.json()
    assert run["passed_count"] == 1
    assert run["failed_count"] == 1
    assert run["results"][0]["run_id"]
    assert run["results"][1]["status"] == "failed"


def test_ml_validation_uses_history_but_returns_only_submitted_predictions(monkeypatch):
    observed_sequences = []

    def fake_predict(readings):
        observed_sequences.append(readings)
        return [
            {
                "reading_index": index,
                "meter_serial_number": reading.get("meter_serial_number"),
                "fault_type": "VALID",
                "fault_confidence": 1.0,
                "is_anomaly": False,
                "anomaly_score": 0.0,
            }
            for index, reading in enumerate(readings)
        ]

    monkeypatch.setattr(ml_routes, "predict_canonical_readings", fake_predict)
    meter_id = f"MTR-HISTORY-{uuid.uuid4().hex}"
    reading = {
        "meter_serial_number": meter_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "active_energy_import_kwh": 12.0,
    }

    first = client.post("/ml/validate", json=reading)
    second = client.post(
        "/ml/validate-batch",
        json={"readings": [{**reading, "active_energy_import_kwh": 13.0}]},
    )

    assert first.status_code == second.status_code == 200
    assert len(observed_sequences[0]) == 1
    assert len(observed_sequences[1]) == 2
    assert second.json()["predictions"][0]["reading_index"] == 0

    with database.SessionLocal() as db:
        rows = db.query(DBMeterHistory).filter(DBMeterHistory.meter_id == meter_id).all()
        assert len(rows) == 2


def test_ml_meter_history_retains_only_the_latest_fifty(monkeypatch):
    observed_sizes = []

    def fake_predict(readings):
        observed_sizes.append(len(readings))
        return [
            {
                "reading_index": index,
                "meter_serial_number": reading.get("meter_serial_number"),
                "fault_type": "VALID",
                "fault_confidence": 1.0,
                "is_anomaly": False,
                "anomaly_score": 0.0,
            }
            for index, reading in enumerate(readings)
        ]

    monkeypatch.setattr(ml_routes, "predict_canonical_readings", fake_predict)
    meter_id = f"MTR-HISTORY-CAP-{uuid.uuid4().hex}"
    readings = [
        {
            "meter_serial_number": meter_id,
            "timestamp": f"2026-01-01T00:{index % 60:02d}:00Z",
            "active_energy_import_kwh": float(index),
        }
        for index in range(51)
    ]

    response = client.post("/ml/validate-batch", json={"readings": readings})
    assert response.status_code == 200

    with database.SessionLocal() as db:
        rows = db.query(DBMeterHistory).filter(DBMeterHistory.meter_id == meter_id).all()
        assert len(rows) == 50

    next_reading = {**readings[-1], "active_energy_import_kwh": 51.0}
    next_response = client.post("/ml/validate", json=next_reading)

    assert next_response.status_code == 200
    assert observed_sizes == [51, 51]
