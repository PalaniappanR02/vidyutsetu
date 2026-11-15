import numpy as np
import pytest

from app.ml.preprocessing import AMIPayloadPreprocessor


def _features(records, rolling_window=10):
    preprocessor = AMIPayloadPreprocessor(rolling_window=rolling_window)
    transformed = preprocessor.fit_transform(records)
    return {
        name: transformed[:, index]
        for index, name in enumerate(preprocessor.feature_names)
    }


def test_distinguishes_absent_keys_from_explicit_nulls():
    features = _features(
        [
            {"meter_id": "M1", "timestamp": "2026-01-01T00:00:00Z"},
            {"meter_id": "M1", "timestamp": "2026-01-01T00:15:00Z", "kwh": None},
        ]
    )

    assert features["missing_key_count"][0] == 8
    assert features["null_count"][0] == 0
    assert features["missing_key_count"][1] == 7
    assert features["null_count"][1] == 1


def test_sequential_features_are_per_meter_and_keep_input_order():
    features = _features(
        [
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:00:00Z",
                "kwh": 10,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M2",
                "timestamp": "2026-01-01T00:00:00Z",
                "kwh": 100,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:15:00Z",
                "kwh": 12,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:30:00Z",
                "kwh": 14,
                "interval_minutes": 15,
            },
        ]
    )

    np.testing.assert_array_equal(features["kwh_delta"], [0, 0, 2, 2])
    np.testing.assert_array_equal(features["interval_ratio"], [0, 0, 1, 1])
    np.testing.assert_array_equal(features["duplicate_key"], [0, 0, 0, 0])
    assert features["kwh_rolling_zscore"][3] > 0


def test_marks_both_duplicate_rows_and_excludes_them_from_meter_history():
    features = _features(
        [
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:00:00Z",
                "kwh": 10,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:15:00Z",
                "kwh": 11,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:15:00Z",
                "kwh": 11,
                "interval_minutes": 15,
            },
            {
                "meter_id": "M1",
                "timestamp": "2026-01-01T00:30:00Z",
                "kwh": 13,
                "interval_minutes": 15,
            },
        ]
    )

    np.testing.assert_array_equal(features["duplicate_key"], [0, 1, 1, 0])
    np.testing.assert_array_equal(features["kwh_delta"], [0, 1, 1, 3])
    np.testing.assert_array_equal(features["interval_ratio"], [0, 1, 1, 2])


def test_malformed_numeric_values_are_flagged_and_input_is_not_modified():
    record = {"meter_id": "M1", "timestamp": "2026-01-01T00:00:00Z", "voltage": "bad"}
    original = record.copy()
    features = _features([record])

    assert features["is_voltage_malformed"][0] == 1
    assert features["voltage_clean"][0] == 230
    assert record == original


def test_rejects_non_positive_rolling_window():
    with pytest.raises(ValueError, match="rolling_window"):
        AMIPayloadPreprocessor(rolling_window=0).fit([])


def test_empty_input_returns_a_matrix_with_the_feature_schema():
    preprocessor = AMIPayloadPreprocessor()

    transformed = preprocessor.transform([])

    assert transformed.shape == (0, len(preprocessor.feature_names))
