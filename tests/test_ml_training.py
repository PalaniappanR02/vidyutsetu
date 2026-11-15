import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.model_selection import GroupKFold

from app.ml.preprocessing import AMIPayloadPreprocessor
from ml_training.train import (
    _anomaly_detector,
    _cross_validate_model,
    _grouped_anomaly_holdout,
    _select_anomaly_threshold,
    _valid_normal_records,
    load_training_data,
    parse_args,
)


class _GroupCheckingClassifier(ClassifierMixin, BaseEstimator):
    def fit(self, X, y):
        self.train_meters_ = set(X["meter_id"])
        self.prediction_ = int(pd.Series(y).mode().iloc[0])
        return self

    def predict(self, X):
        assert self.train_meters_.isdisjoint(set(X["meter_id"]))
        return np.full(len(X), self.prediction_)


def _write_csv(tmp_path, rows):
    csv_path = tmp_path / "training.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


def test_loads_complete_synthetic_training_csv(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "meter_id": "M1",
                "fault_label": "VALID",
                "is_anomaly_label": 0,
                "is_synthetic": 1,
            },
            {
                "meter_id": "M2",
                "fault_label": "WRONG_DATATYPE",
                "is_anomaly_label": 1,
                "is_synthetic": 1,
            },
        ],
    )

    data = load_training_data(csv_path)

    assert len(data) == 2
    assert data["is_anomaly_label"].tolist() == [0, 1]


def test_rejects_csv_missing_training_labels(tmp_path):
    csv_path = _write_csv(tmp_path, [{"meter_id": "M1", "fault_label": "VALID"}])

    with pytest.raises(ValueError, match="is_anomaly_label"):
        load_training_data(csv_path)


def test_rejects_rows_not_marked_synthetic(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        [
            {
                "meter_id": "M1",
                "fault_label": "VALID",
                "is_anomaly_label": 0,
                "is_synthetic": 0,
            },
            {
                "meter_id": "M2",
                "fault_label": "WRONG_DATATYPE",
                "is_anomaly_label": 1,
                "is_synthetic": 1,
            },
        ],
    )

    with pytest.raises(ValueError, match="SYNTHETIC"):
        load_training_data(csv_path)


def test_quick_flag_is_optional(monkeypatch):
    monkeypatch.setattr("sys.argv", ["train.py", "--data-csv", "training.csv", "--quick"])

    assert parse_args().quick is True


def test_quick_flag_defaults_to_false(monkeypatch):
    monkeypatch.setattr("sys.argv", ["train.py", "--data-csv", "training.csv"])

    assert parse_args().quick is False


def test_anomaly_detector_uses_valid_consumption_features_and_f1_threshold():
    records = pd.DataFrame(
        [
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:00:00Z",
                "kwh": 10,
                "voltage": 230,
                "fault_label": "VALID",
                "is_anomaly_label": 0,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:15:00Z",
                "kwh": 12,
                "voltage": 232,
                "fault_label": "VALID",
                "is_anomaly_label": 0,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:30:00Z",
                "kwh": 100,
                "voltage": 300,
                "fault_label": "OUT_OF_RANGE_VALUE",
                "is_anomaly_label": 0,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:45:00Z",
                "kwh": 14,
                "voltage": 234,
                "fault_label": "VALID",
                "is_anomaly_label": 1,
            },
        ]
    )

    normal_records = _valid_normal_records(records)
    detector_features = _anomaly_detector(seed=42, quick=True)[:-1]
    transformed = detector_features.fit_transform(normal_records)
    selected_names = ("kwh_delta", "voltage_clean", "kwh_rolling_zscore")
    expected = AMIPayloadPreprocessor().fit_transform(normal_records)[
        :,
        [AMIPayloadPreprocessor.feature_names.index(name) for name in selected_names],
    ]
    np.testing.assert_array_equal(transformed, expected)
    assert len(normal_records) == 2

    scores = np.array([-0.3, 0.1, 0.2, 0.5])
    labels = np.array([0, 0, 1, 1])
    threshold = _select_anomaly_threshold(scores, labels)
    assert threshold == 0.2
    assert (scores >= threshold).tolist() == [False, False, True, True]


def test_cross_validation_keeps_meter_groups_disjoint():
    records = pd.DataFrame(
        {"meter_id": [f"M{i}" for i in range(6)], "reading": range(6)}
    )
    labels = np.array([0, 1, 0, 1, 0, 1])
    groups = records["meter_id"].to_numpy()

    _cross_validate_model(
        _GroupCheckingClassifier(),
        records,
        labels,
        GroupKFold(n_splits=3),
        groups,
    )


def test_anomaly_threshold_validation_split_is_meter_disjoint():
    records = pd.DataFrame(
        [
            {
                "meter_id": meter_id,
                "fault_label": "VALID",
                "is_anomaly_label": anomaly_label,
            }
            for meter_id in (f"M{i}" for i in range(8))
            for anomaly_label in (0, 1)
        ]
    )

    train_indices, validation_indices = _grouped_anomaly_holdout(records, seed=42)

    assert set(records.iloc[train_indices]["meter_id"]).isdisjoint(
        set(records.iloc[validation_indices]["meter_id"])
    )
    assert set(records.iloc[validation_indices]["is_anomaly_label"]) == {0, 1}
