"""Batch B: labelled findings, meter behaviour profiling, drift and SHAP explanations."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.ml import inference
from app.ml.preprocessing import AMIPayloadPreprocessor
from backend.api import ml_routes
from backend.db import database
from backend.main import app

client = TestClient(app)


@pytest.fixture
def fake_predict(monkeypatch):
    def _predict(readings):
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

    monkeypatch.setattr(ml_routes, "predict_canonical_readings", _predict)


def _reading(meter_id: str, kwh: float, timestamp: str) -> dict:
    return {
        "meter_serial_number": meter_id,
        "timestamp": timestamp,
        "active_energy_import_kwh": kwh,
        "voltage_v": 230.0,
        "current_a": 4.0,
        "power_factor": 0.95,
        "frequency_hz": 50.0,
    }


def _faulty_workbench_payload() -> str:
    return json.dumps(
        {
            "telemetry": [
                {
                    "device_uid": "MTR-FINDINGS",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "act_wh": -1000,
                }
            ]
        }
    )


def test_workbench_findings_all_carry_severity_confidence_explanation_and_source():
    response = client.post(
        "/api/workbench/execute",
        data={"source_vendor": "delta-legacy", "raw_payload": _faulty_workbench_payload()},
    )
    assert response.status_code == 200
    findings = response.json()["findings"]

    assert findings
    for finding in findings:
        assert finding["severity"] in {"ERROR", "WARNING", "INFO"}
        assert 0.0 <= finding["confidence"] <= 1.0
        assert finding["explanation"].strip()
        assert finding["source"] in {"rule", "ml"}
        assert finding["confidence_source"]

    rule_findings = [f for f in findings if f["source"] == "rule"]
    ml_findings = [f for f in findings if f["source"] == "ml"]
    assert rule_findings and ml_findings
    assert all(f["confidence"] == 1.0 for f in rule_findings)
    assert all(f["confidence_source"] == "deterministic_rule" for f in rule_findings)
    assert all(
        f["confidence_source"] == "fault_classifier_probability" for f in ml_findings
    )


def test_ml_validate_findings_carry_the_same_labelling():
    response = client.post(
        "/ml/validate",
        json={
            "meter_serial_number": "MTR-FINDINGS-ML",
            "timestamp": "2026-01-01T00:00:00Z",
            "active_energy_import_kwh": -5.0,
        },
    )

    assert response.status_code == 200
    findings = response.json()["findings"]
    assert findings
    for finding in findings:
        assert finding["source"] == "ml"
        assert finding["severity"] == "WARNING"
        assert 0.0 <= finding["confidence"] <= 1.0
        assert finding["explanation"]
        assert finding["code"]


def test_meter_profile_is_computed_from_stored_history(fake_predict):
    meter_id = f"MTR-PROFILE-{uuid.uuid4().hex}"
    stored = [10.0, 10.5, 20.0, 20.5]
    for index, kwh in enumerate(stored):
        response = client.post(
            "/ml/validate",
            json=_reading(meter_id, kwh, f"2026-01-01T0{index}:00:00Z"),
        )
        assert response.status_code == 200

    meters = client.get("/ml/meters").json()
    listed = next(item for item in meters if item["meter_id"] == meter_id)
    assert listed["reading_count"] == 4

    profile = client.get(f"/ml/meters/{meter_id}/profile").json()
    assert profile["meter_id"] == meter_id
    assert profile["readings_used"] == 4
    assert profile["energy_kwh"]["mean"] == pytest.approx(15.25)
    assert profile["energy_kwh"]["min"] == 10.0
    assert profile["energy_kwh"]["max"] == 20.5
    assert profile["voltage_v"]["mean"] == pytest.approx(230.0)
    assert profile["source"] == "rule"
    assert profile["arrival_order"] is True


def test_meter_profile_reports_drift_across_arrival_windows(fake_predict):
    meter_id = f"MTR-DRIFT-{uuid.uuid4().hex}"
    # Timestamps descend while values rise: only arrival order can produce +5 kWh.
    readings = [
        ("2026-01-01T03:00:00Z", 10.0),
        ("2026-01-01T02:00:00Z", 10.0),
        ("2026-01-01T01:00:00Z", 20.0),
        ("2026-01-01T00:00:00Z", 20.0),
    ]
    for timestamp, kwh in readings:
        assert client.post("/ml/validate", json=_reading(meter_id, kwh, timestamp)).status_code == 200

    drift = client.get(f"/ml/meters/{meter_id}/profile").json()["drift"]

    assert drift["basis"] == "stored_history_arrival_order"
    # Arrival-order windows: first two readings mean 10.0, last two mean 20.0.
    assert drift["energy_kwh"]["baseline_mean"] == pytest.approx(10.0)
    assert drift["energy_kwh"]["recent_mean"] == pytest.approx(20.0)
    assert drift["energy_kwh"]["delta"] == pytest.approx(10.0)
    assert drift["energy_kwh"]["direction"] == "increase"
    assert drift["energy_kwh"]["exceeds_threshold"] is True
    assert "energy_kwh" in drift["flagged_metrics"]
    assert drift["window_size"] == 2
    assert set(drift["thresholds"]) == {"energy_kwh", "voltage_v", "power_factor", "frequency_hz"}


def test_meter_profile_returns_404_for_unknown_meter():
    response = client.get("/ml/meters/MTR-DOES-NOT-EXIST/profile")

    assert response.status_code == 404
    assert "history" in response.json()["detail"]


def test_ml_explain_reports_method_and_feature_scores():
    response = client.post(
        "/ml/explain",
        json={
            "readings": [
                {
                    "meter_serial_number": "MTR-SHAP",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "active_energy_import_kwh": 12.5,
                    "voltage_v": 600.0,
                    "frequency_hz": 999.9,
                    "power_factor": 2.3,
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_synthetic"] is True
    assert body["method"] in {
        "shap_tree_explainer",
        "feature_importance_approximation",
    }
    explanation = body["explanations"][0]
    assert explanation["reading_index"] == 0
    assert explanation["predicted_fault_type"]
    assert 1 <= len(explanation["top_features"]) <= 3
    known_features = set(AMIPayloadPreprocessor.feature_names)
    for feature in explanation["top_features"]:
        assert feature["feature"] in known_features
        assert isinstance(feature["contribution"], float)


def test_ml_explain_rejects_an_empty_batch():
    response = client.post("/ml/explain", json={"readings": []})

    assert response.status_code == 422


def test_ml_explain_labels_importance_fallback_when_shap_is_unavailable(monkeypatch):
    monkeypatch.setattr(inference, "_load_shap_explainer", lambda _path: None)

    response = client.post(
        "/ml/explain",
        json={"readings": [{"meter_serial_number": "MTR-FALLBACK", "voltage_v": 600}]},
    )

    assert response.status_code == 200
    assert response.json()["method"] == "feature_importance_approximation"


def test_ml_health_metrics_are_not_rewritten_by_analytics():
    health = client.get("/ml/health").json()

    assert health["metrics"]["shap"]["status"] == "skipped"
    assert health["is_synthetic"] is True
