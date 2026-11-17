"""Lazy inference service for the synthetic AMI fault and anomaly models."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILES = {
    "fault_classifier": "fault_classifier.joblib",
    "anomaly_detector": "anomaly_detector.joblib",
    "label_encoder": "label_encoder.joblib",
}


class MLArtifactsError(RuntimeError):
    """Raised when the model artifacts are unavailable or inconsistent."""


def canonical_reading_to_features(reading: Any) -> dict[str, Any]:
    """Map a canonical reading to the input fields expected by the preprocessor."""
    if isinstance(reading, Mapping):
        canonical = dict(reading)
    elif hasattr(reading, "model_dump"):
        canonical = reading.model_dump(mode="json")
    else:
        raise TypeError("reading must be a mapping or a Pydantic model")

    field_mapping = {
        "meter_serial_number": "meter_id",
        "timestamp": "timestamp",
        "active_energy_import_kwh": "kwh",
        "apparent_energy_kvah": "kvah",
        "voltage_v": "voltage",
        "current_a": "current",
        "power_factor": "power_factor",
        "frequency_hz": "frequency",
        "interval_minutes": "interval_minutes",
    }
    features = {target: canonical.get(source) for source, target in field_mapping.items()}
    if "payload_size_bytes" in canonical:
        features["payload_size_bytes"] = canonical["payload_size_bytes"]
    else:
        serialized = json.dumps(canonical, separators=(",", ":"), default=str)
        features["payload_size_bytes"] = len(serialized.encode("utf-8"))
    return features


def _read_artifact_metadata(artifacts_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    required = (*MODEL_FILES.values(), "feature_schema.json", "metrics.json")
    for filename in required:
        path = artifacts_dir / filename
        if not path.is_file():
            raise MLArtifactsError(f"Required ML artifact is missing: {path}")

    try:
        schema = json.loads((artifacts_dir / "feature_schema.json").read_text(encoding="utf-8"))
        metrics = json.loads((artifacts_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MLArtifactsError(f"Unable to read ML artifact metadata: {error}") from error
    if not isinstance(schema, dict) or not isinstance(metrics, dict):
        raise MLArtifactsError("ML artifact metadata must contain JSON objects")
    return schema, metrics


def get_ml_health() -> dict[str, Any]:
    schema, metrics = _read_artifact_metadata(ARTIFACTS_DIR)
    model_versions = {
        name: hashlib.sha256((ARTIFACTS_DIR / filename).read_bytes()).hexdigest()
        for name, filename in MODEL_FILES.items()
    }
    training_data = schema.get("training_data")
    is_synthetic = (
        training_data == "SYNTHETIC"
        or isinstance(training_data, dict) and training_data.get("type") == "SYNTHETIC"
    )
    return {
        "status": "ready",
        "model_versions": model_versions,
        "metrics": metrics,
        "is_synthetic": is_synthetic,
    }


@lru_cache(maxsize=4)
def _load_models(artifacts_dir: str) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
    artifact_path = Path(artifacts_dir)
    schema, metrics = _read_artifact_metadata(artifact_path)

    try:
        import joblib

        classifier = joblib.load(artifact_path / MODEL_FILES["fault_classifier"])
        detector = joblib.load(artifact_path / MODEL_FILES["anomaly_detector"])
        label_encoder = joblib.load(artifact_path / MODEL_FILES["label_encoder"])
    except FileNotFoundError as error:
        raise MLArtifactsError(f"Required ML artifact is missing: {error.filename}") from error

    expected_features = [feature["name"] for feature in schema.get("features", [])]
    preprocessor = classifier.named_steps["preprocessor"]
    actual_features = list(preprocessor.get_feature_names_out())
    if expected_features != actual_features:
        raise MLArtifactsError("Feature schema does not match the saved classifier preprocessor")

    return classifier, detector, label_encoder, schema, metrics


def predict_canonical_readings(readings: Sequence[Any]) -> list[dict[str, Any]]:
    if not readings:
        return []

    classifier, detector, label_encoder, _schema, metrics = _load_models(
        str(ARTIFACTS_DIR.resolve())
    )
    records = [canonical_reading_to_features(reading) for reading in readings]

    encoded_predictions = classifier.predict(records)
    probabilities = classifier.predict_proba(records)
    classifier_classes = classifier.named_steps["classifier"].classes_
    decoded_classes = label_encoder.inverse_transform(
        [int(class_index) for class_index in classifier_classes]
    )
    predicted_labels = label_encoder.inverse_transform(
        [int(class_index) for class_index in encoded_predictions]
    )

    anomaly_scores = -detector.decision_function(records)
    anomaly_threshold = metrics["anomaly_detection"]["test"]["threshold"]
    results_by_index = {}
    for original_index, label, probability_row, anomaly_score in zip(
        range(len(readings)), predicted_labels, probabilities, anomaly_scores, strict=True
    ):
        predicted_class_index = list(decoded_classes).index(label)
        reading = readings[original_index]
        meter_id = (
            reading.get("meter_serial_number")
            if isinstance(reading, Mapping)
            else getattr(reading, "meter_serial_number", None)
        )
        results_by_index[original_index] = {
            "reading_index": original_index,
            "meter_serial_number": meter_id,
            "fault_type": str(label),
            "fault_confidence": float(probability_row[predicted_class_index]),
            "is_anomaly": bool(anomaly_score >= anomaly_threshold),
            "anomaly_score": float(anomaly_score),
        }
    return [results_by_index[index] for index in range(len(readings))]

def make_ml_findings(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for prediction in predictions:
        index = prediction["reading_index"]
        confidence = float(prediction["fault_confidence"])
        if prediction["fault_type"] != "VALID":
            findings.append(
                {
                    "code": "ML_FAULT_CLASSIFICATION",
                    "field": f"readings[{index}]",
                    "severity": "WARNING",
                    "message": (
                        f"ML classifier predicted {prediction['fault_type']} "
                        f"(confidence {confidence:.3f})."
                    ),
                    "explanation": (
                        f"The learned fault classifier (trained on synthetic data) "
                        f"assigned {prediction['fault_type']} with probability "
                        f"{confidence:.3f}. It screens for review; it does not decide "
                        f"conformance and does not override rule results."
                    ),
                    "confidence": confidence,
                    "confidence_source": "fault_classifier_probability",
                    "observed_value": dict(prediction),
                    "source": "ml",
                }
            )
        if prediction["is_anomaly"]:
            findings.append(
                {
                    "code": "ML_ANOMALY_SCREENING",
                    "field": f"readings[{index}]",
                    "severity": "WARNING",
                    "message": "Flagged by the high-recall ML anomaly screen; review is recommended.",
                    "explanation": (
                        "The IsolationForest screen flagged this reading for review. "
                        "The stated confidence is the fault classifier's probability for "
                        "the same reading; this is a screening indicator, not a confirmed "
                        "fault."
                    ),
                    "confidence": confidence,
                    "confidence_source": "fault_classifier_probability",
                    "observed_value": dict(prediction),
                    "source": "ml",
                }
            )
    return findings


@lru_cache(maxsize=2)
def _load_shap_explainer(artifacts_dir: str) -> Any:
    """Build a SHAP tree explainer over the *existing* classifier (no retraining)."""
    import shap

    classifier, _detector, _label_encoder, _schema, _metrics = _load_models(artifacts_dir)
    return shap.TreeExplainer(classifier.named_steps["classifier"])


def explain_canonical_readings(
    readings: Sequence[Any], top_k: int = 3
) -> list[dict[str, Any]]:
    """SHAP contributions for the predicted class of each reading.

    Explains the saved XGBoost classifier only; nothing is retrained and the
    artifact files are opened read-only.
    """
    if not readings:
        return []

    classifier, _detector, label_encoder, _schema, _metrics = _load_models(
        str(ARTIFACTS_DIR.resolve())
    )
    explainer = _load_shap_explainer(str(ARTIFACTS_DIR.resolve()))
    preprocessor = classifier.named_steps["preprocessor"]
    records = [canonical_reading_to_features(reading) for reading in readings]
    transformed = preprocessor.transform(records)
    feature_names = list(preprocessor.get_feature_names_out())
    contributions = np.asarray(explainer.shap_values(transformed))
    if contributions.ndim == 2:
        contributions = contributions[:, :, np.newaxis]

    encoded_predictions = classifier.predict(records)
    classifier_classes = list(classifier.named_steps["classifier"].classes_)
    explanations: list[dict[str, Any]] = []
    for index, (encoded, record) in enumerate(zip(encoded_predictions, records, strict=True)):
        class_position = classifier_classes.index(encoded)
        per_feature = contributions[index][:, class_position]
        order = np.argsort(-np.abs(per_feature))[:top_k]
        explanations.append(
            {
                "reading_index": index,
                "meter_serial_number": record.get("meter_id"),
                "predicted_fault_type": str(
                    label_encoder.inverse_transform([int(encoded)])[0]
                ),
                "top_features": [
                    {
                        "feature": feature_names[position],
                        "contribution": float(per_feature[position]),
                    }
                    for position in order
                ],
            }
        )
    return explanations
