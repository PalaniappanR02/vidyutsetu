import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.ml.inference as inference
from app.ml.inference import canonical_reading_to_features
from backend.main import app


client = TestClient(app)


def _reading(meter_id: str) -> dict:
    return {
        "meter_serial_number": meter_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "interval_minutes": 15,
        "active_energy_import_kwh": 12.5,
        "apparent_energy_kvah": 13.0,
        "voltage_v": 230.0,
        "current_a": 4.0,
        "power_factor": 0.95,
        "frequency_hz": 50.0,
    }


def test_canonical_reading_fields_map_to_preprocessor_inputs():
    features = canonical_reading_to_features(_reading("MTR-1"))

    assert features["meter_id"] == "MTR-1"
    assert features["kwh"] == 12.5
    assert features["kvah"] == 13.0
    assert features["voltage"] == 230.0
    assert features["frequency"] == 50.0
    assert features["payload_size_bytes"] > 0


def test_ml_validate_accepts_malformed_numeric_values():
    reading = _reading("MTR-1")
    reading["active_energy_import_kwh"] = "not-a-number"

    response = client.post("/ml/validate", json=reading)

    assert response.status_code == 200
    body = response.json()
    assert body["is_synthetic"] is True
    assert body["prediction"]["fault_type"]
    assert 0.0 <= body["prediction"]["fault_confidence"] <= 1.0
    assert all(finding["source"] == "ml" for finding in body["findings"])


def test_ml_batch_preserves_reading_order():
    response = client.post(
        "/ml/validate-batch",
        json={"readings": [_reading("MTR-2"), _reading("MTR-1")]},
    )

    assert response.status_code == 200
    assert [
        prediction["meter_serial_number"]
        for prediction in response.json()["predictions"]
    ] == ["MTR-2", "MTR-1"]


def test_ml_sequence_features_are_timestamp_ordered_and_results_keep_input_order():
    earlier = _reading("MTR-1")
    earlier["timestamp"] = "2026-01-01T00:00:00Z"
    earlier["active_energy_import_kwh"] = 10.0
    later = _reading("MTR-1")
    later["timestamp"] = "2026-01-01T00:15:00Z"
    later["active_energy_import_kwh"] = 14.0

    unsorted_response = client.post(
        "/ml/validate-batch",
        json={"readings": [later, earlier]},
    )
    sorted_response = client.post(
        "/ml/validate-batch",
        json={"readings": [earlier, later]},
    )

    assert unsorted_response.status_code == sorted_response.status_code == 200
    unsorted_results = unsorted_response.json()["predictions"]
    sorted_results = sorted_response.json()["predictions"]
    assert [result["reading_index"] for result in unsorted_results] == [0, 1]
    for unsorted_result, sorted_result in zip(
        unsorted_results, reversed(sorted_results), strict=True
    ):
        assert unsorted_result["fault_type"] == sorted_result["fault_type"]
        assert unsorted_result["fault_confidence"] == sorted_result["fault_confidence"]
        assert unsorted_result["anomaly_score"] == sorted_result["anomaly_score"]


def test_ml_health_reads_metrics_and_reports_artifact_versions():
    response = client.get("/ml/health")

    assert response.status_code == 200
    body = response.json()
    metrics_path = Path(__file__).parents[1] / "app" / "ml" / "artifacts" / "metrics.json"
    assert body["metrics"] == json.loads(metrics_path.read_text(encoding="utf-8"))
    assert body["is_synthetic"] is True
    assert set(body["model_versions"]) == {
        "fault_classifier",
        "anomaly_detector",
        "label_encoder",
    }


def test_ml_health_reports_missing_artifacts_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(inference, "ARTIFACTS_DIR", tmp_path)

    response = client.get("/ml/health")

    assert response.status_code == 503
    assert "Required ML artifact is missing" in response.json()["detail"]
    assert "fault_classifier.joblib" in response.json()["detail"]


def test_ml_validate_reports_missing_artifacts_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(inference, "ARTIFACTS_DIR", tmp_path)

    response = client.post("/ml/validate", json=_reading("MTR-1"))

    assert response.status_code == 503
    assert "Required ML artifact is missing" in response.json()["detail"]


def test_workbench_adds_ml_findings_without_changing_score_shape():
    payload = {
        "telemetry": [
            {
                "device_uid": "MTR-NEGATIVE",
                "timestamp": "2026-01-01T00:00:00Z",
                "act_wh": -1000,
            }
        ]
    }
    response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(payload),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert {"total_score", "grade", "summary"} <= set(body["score"])
    assert body["ml_results"][0]["reading_index"] == 0
    assert any(finding["source"] == "rule" for finding in body["findings"])
    assert any(issue["code"] == "NEGATIVE_ACTIVE_ENERGY" for issue in body["issues"])
    assert all(finding["source"] == "ml" for finding in body["ml_findings"])


def test_workbench_keeps_rule_results_available_when_ml_artifacts_are_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(inference, "ARTIFACTS_DIR", tmp_path)
    payload = {
        "telemetry": [
            {
                "device_uid": "MTR-NEGATIVE",
                "timestamp": "2026-01-01T00:00:00Z",
                "act_wh": -1000,
            }
        ]
    }

    response = client.post(
        "/api/workbench/execute",
        data={
            "source_vendor": "delta-legacy",
            "raw_payload": json.dumps(payload),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert any(issue["code"] == "NEGATIVE_ACTIVE_ENERGY" for issue in body["issues"])
    assert body["score"]["total_score"] < 100
    assert body["ml_results"] == []
    assert "Required ML artifact is missing" in body["ml_error"]
