import json
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sklearn.preprocessing import LabelEncoder

import app.ml.inference as inference
from app.ml.inference import canonical_reading_to_features
from backend.main import app
from ml_training.train import FAULT_LABEL, _grouped_holdout, load_training_data


client = TestClient(app)
_reading_sequence = count()


def _reading(meter_id: str) -> dict:
    return {
        "meter_serial_number": meter_id,
        "timestamp": (
            datetime.now(timezone.utc) + timedelta(seconds=next(_reading_sequence))
        ).isoformat(),
        "interval_minutes": 15,
        "active_energy_import_kwh": 12.5,
        "apparent_energy_kvah": 13.0,
        "voltage_v": 230.0,
        "current_a": 4.0,
        "power_factor": 0.95,
        "frequency_hz": 50.0,
    }


def _canonical_readings_from_training_rows(rows: list[dict]) -> list[dict]:
    field_mapping = {
        "meter_id": "meter_serial_number",
        "timestamp": "timestamp",
        "kwh": "active_energy_import_kwh",
        "kvah": "apparent_energy_kvah",
        "voltage": "voltage_v",
        "current": "current_a",
        "power_factor": "power_factor",
        "frequency": "frequency_hz",
        "interval_minutes": "interval_minutes",
        "payload_size_bytes": "payload_size_bytes",
    }
    return [
        {
            canonical_name: row[source_name]
            for source_name, canonical_name in field_mapping.items()
        }
        for row in rows
    ]


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


def test_ml_validate_returns_valid_for_a_valid_payload():
    response = client.post("/ml/validate", json=_reading("MTR-VALID"))

    assert response.status_code == 200
    assert response.json()["prediction"]["fault_type"] == "VALID"


def test_ml_validate_classifies_missing_field():
    reading = _reading("MTR-MISSING")
    del reading["active_energy_import_kwh"]

    response = client.post("/ml/validate", json=reading)

    assert response.status_code == 200
    assert response.json()["prediction"]["fault_type"] == "MISSING_FIELD"


def test_ml_validate_classifies_wrong_datatype_without_rejecting_request():
    reading = _reading("MTR-DATATYPE")
    reading["voltage_v"] = "230V"
    reading["frequency_hz"] = "50Hz"

    response = client.post("/ml/validate", json=reading)

    assert response.status_code == 200
    assert response.json()["prediction"]["fault_type"] == "WRONG_DATATYPE"


def test_ml_validate_classifies_out_of_range_values():
    reading = _reading("MTR-RANGE")
    reading["voltage_v"] = 600
    reading["frequency_hz"] = 999.9
    reading["power_factor"] = 2.3

    response = client.post("/ml/validate", json=reading)

    assert response.status_code == 200
    assert response.json()["prediction"]["fault_type"] == "OUT_OF_RANGE_VALUE"


def test_ml_validate_batch_classifies_duplicate_readings():
    first = _reading("MTR-DUPLICATE")
    duplicate = first.copy()

    response = client.post(
        "/ml/validate-batch",
        json={"readings": [first, duplicate]},
    )

    assert response.status_code == 200
    assert [item["fault_type"] for item in response.json()["predictions"]] == [
        "DUPLICATE_READING",
        "DUPLICATE_READING",
    ]


def test_ml_validate_batch_classifies_backward_and_gapped_timestamps_in_arrival_order():
    records = load_training_data(
        Path(__file__).parents[1] / "data" / "ami_payload_dataset_synthetic.csv"
    )
    sequences = {"backward": None, "gap": None}
    previous_by_meter = {}
    for row in records.to_dict(orient="records"):
        meter_id = row["meter_id"]
        previous = previous_by_meter.get(meter_id)
        if previous is not None and row[FAULT_LABEL] == "TIMESTAMP_DRIFT_OR_GAP":
            elapsed = (
                pd.Timestamp(row["timestamp"]) - pd.Timestamp(previous["timestamp"])
            ).total_seconds() / 3600
            if elapsed < 0 and sequences["backward"] is None:
                sequences["backward"] = [previous, row]
            elif elapsed >= 3 and sequences["gap"] is None:
                sequences["gap"] = [previous, row]
        previous_by_meter[meter_id] = row

    assert sequences["backward"] is not None
    assert sequences["gap"] is not None
    readings = _canonical_readings_from_training_rows(
        sequences["backward"] + sequences["gap"]
    )
    predictions = inference.predict_canonical_readings(readings)

    assert predictions[1]["fault_type"] == "TIMESTAMP_DRIFT_OR_GAP"
    assert predictions[3]["fault_type"] == "TIMESTAMP_DRIFT_OR_GAP"


def test_ml_validate_batch_classifies_negative_or_rollback_kwh():
    first = _reading("MTR-ROLLBACK")
    first["active_energy_import_kwh"] = 500
    second = _reading("MTR-ROLLBACK")
    second["timestamp"] = "2026-01-01T00:15:00Z"
    second["active_energy_import_kwh"] = -10

    response = client.post(
        "/ml/validate-batch",
        json={"readings": [first, second]},
    )

    assert response.status_code == 200
    assert response.json()["predictions"][1]["fault_type"] == "NEGATIVE_OR_ROLLBACK_KWH"


def test_ml_validate_batch_classifies_unit_mismatch_in_meter_sequence():
    readings = [_reading("MTR-UNIT") for _ in range(3)]
    for index, reading in enumerate(readings):
        reading["timestamp"] = f"2026-01-01T00:{index * 15:02d}:00Z"
        reading["active_energy_import_kwh"] = 12.5 + index * 0.1
        reading["apparent_energy_kvah"] = 13.0 + index * 0.1
    readings[2]["active_energy_import_kwh"] = 12500
    readings[2]["apparent_energy_kvah"] = 13000

    response = client.post("/ml/validate-batch", json={"readings": readings})

    assert response.status_code == 200
    assert response.json()["predictions"][2]["fault_type"] == "UNIT_MISMATCH"


def test_inference_recall_matches_metrics_for_seed_42_held_out_meters():
    data_path = Path(__file__).parents[1] / "data" / "ami_payload_dataset_synthetic.csv"
    records = load_training_data(data_path)
    encoder = LabelEncoder()
    encoded_labels = encoder.fit_transform(records[FAULT_LABEL].astype(str))
    _train_indices, test_indices = _grouped_holdout(records, encoded_labels, 0.2, seed=42)
    held_out = records.iloc[test_indices]
    readings = _canonical_readings_from_training_rows(held_out.to_dict(orient="records"))

    predictions = inference.predict_canonical_readings(readings)
    metrics = inference.get_ml_health()["metrics"]
    expected_recalls = metrics["fault_classification"]["test"][
        metrics["selected_classifier"]
    ]["classification_report"]
    for fault_type in encoder.classes_:
        true_positives = sum(
            prediction["fault_type"] == fault_type and actual == fault_type
            for prediction, actual in zip(predictions, held_out[FAULT_LABEL], strict=True)
        )
        support = int((held_out[FAULT_LABEL] == fault_type).sum())
        recall = true_positives / support
        expected_recall = expected_recalls[fault_type]["recall"]
        assert abs(recall - expected_recall) <= 0.03, (
            f"{fault_type} recall {recall:.3f} differs from metrics.json "
            f"{expected_recall:.3f} by more than 3 percentage points"
        )


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


def test_ml_sequence_features_follow_arrival_order_and_results_keep_input_order():
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
    assert [result["reading_index"] for result in sorted_results] == [0, 1]
    assert unsorted_results[0]["fault_confidence"] != sorted_results[1]["fault_confidence"]


def test_ml_health_reads_metrics_and_reports_artifact_versions():
    response = client.get("/ml/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"]
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
