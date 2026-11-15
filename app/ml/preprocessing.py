"""Shared, importable preprocessing for AMI payload classification."""

from collections.abc import Mapping, Sequence
from math import isfinite, sqrt
from typing import Any

import pandas as pd


class AMIPayloadPreprocessor:
    """Convert AMI records into numeric features, preserving row order."""

    input_fields = (
        "meter_id",
        "timestamp",
        "kwh",
        "kvah",
        "voltage",
        "current",
        "power_factor",
        "frequency",
        "interval_minutes",
        "payload_size_bytes",
    )
    feature_names = (
        "missing_key_count",
        "null_count",
        "voltage_clean",
        "kwh_clean",
        "frequency_clean",
        "current_clean",
        "pf_clean",
        "payload_size_bytes",
        "is_voltage_malformed",
        "is_frequency_malformed",
        "is_kwh_malformed",
        "is_current_malformed",
        "is_pf_malformed",
        "is_payload_size_malformed",
        "is_freq_out_of_range",
        "is_kwh_negative",
        "kwh_delta",
        "interval_ratio",
        "duplicate_key",
        "kwh_rolling_zscore",
    )

    def __init__(self, rolling_window: int = 10):
        self.rolling_window = rolling_window

    def fit(self, X: Any, y: Any = None) -> "AMIPayloadPreprocessor":
        if not isinstance(self.rolling_window, int) or self.rolling_window < 1:
            raise ValueError("rolling_window must be a positive integer")
        return self

    def fit_transform(self, X: Any, y: Any = None) -> Any:
        return self.fit(X, y).transform(X)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return {"rolling_window": self.rolling_window}

    def set_params(self, **params: Any) -> "AMIPayloadPreprocessor":
        unexpected = set(params) - {"rolling_window"}
        if unexpected:
            raise ValueError(f"Unknown parameter(s): {', '.join(sorted(unexpected))}")
        for name, value in params.items():
            setattr(self, name, value)
        return self

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        return pd.Index(self.feature_names, dtype="object")

    def transform(self, X: Any) -> Any:
        self.fit(X)
        records = self._records(X)
        meter_history: dict[str, dict[str, Any]] = {}
        reading_keys = [self._reading_key(record) for record in records]
        seen_reading_keys: set[tuple[str, str]] = set()
        duplicate_reading_keys: set[tuple[str, str]] = set()
        for reading_key in reading_keys:
            if reading_key is not None:
                if reading_key in seen_reading_keys:
                    duplicate_reading_keys.add(reading_key)
                seen_reading_keys.add(reading_key)
        output: list[list[float]] = []

        for record, reading_key in zip(records, reading_keys, strict=True):
            missing_count = sum(field not in record for field in self.input_fields)
            null_count = sum(
                field in record and self._is_null(record[field])
                for field in self.input_fields
            )

            voltage, voltage_valid = self._number(record, "voltage")
            kwh, kwh_valid = self._number(record, "kwh")
            frequency, frequency_valid = self._number(record, "frequency")
            current, current_valid = self._number(record, "current")
            power_factor, power_factor_valid = self._number(record, "power_factor")
            payload_size, payload_size_valid = self._number(record, "payload_size_bytes")
            interval, interval_valid = self._number(record, "interval_minutes")

            meter_value = record.get("meter_id")
            meter_id = None if self._is_null(meter_value) else str(meter_value)
            timestamp_value = record.get("timestamp")
            timestamp = self._timestamp(timestamp_value)

            delta = 0.0
            interval_ratio = 0.0
            duplicate_key = 0.0
            rolling_zscore = 0.0
            history = meter_history.get(meter_id) if meter_id is not None else None

            if reading_key is not None:
                duplicate_key = float(reading_key in duplicate_reading_keys)

            if history is not None:
                previous_kwh = history["kwh"]
                if kwh_valid and previous_kwh is not None:
                    delta = kwh - previous_kwh

                previous_timestamp = history["timestamp"]
                if (
                    timestamp is not None
                    and previous_timestamp is not None
                    and interval_valid
                    and interval > 0
                ):
                    elapsed_minutes = (timestamp - previous_timestamp).total_seconds() / 60.0
                    interval_ratio = elapsed_minutes / interval

                previous_values = history["kwh_values"][-self.rolling_window :]
                if kwh_valid and previous_values:
                    mean = sum(previous_values) / len(previous_values)
                    variance = sum((value - mean) ** 2 for value in previous_values) / len(
                        previous_values
                    )
                    standard_deviation = sqrt(variance)
                    if standard_deviation > 0:
                        rolling_zscore = (kwh - mean) / standard_deviation

            output.append(
                [
                    float(missing_count),
                    float(null_count),
                    voltage if voltage_valid else 230.0,
                    kwh if kwh_valid else 0.0,
                    frequency if frequency_valid else 50.0,
                    current if current_valid else 0.0,
                    power_factor if power_factor_valid else 0.95,
                    payload_size if payload_size_valid else 250.0,
                    float(self._malformed(record, "voltage", voltage_valid)),
                    float(self._malformed(record, "frequency", frequency_valid)),
                    float(self._malformed(record, "kwh", kwh_valid)),
                    float(self._malformed(record, "current", current_valid)),
                    float(self._malformed(record, "power_factor", power_factor_valid)),
                    float(self._malformed(record, "payload_size_bytes", payload_size_valid)),
                    float(frequency_valid and not 45.0 <= frequency <= 55.0),
                    float(kwh_valid and kwh < 0),
                    delta,
                    interval_ratio,
                    duplicate_key,
                    rolling_zscore,
                ]
            )

            if meter_id is not None and not duplicate_key:
                if history is None:
                    history = {"kwh": None, "timestamp": None, "kwh_values": []}
                    meter_history[meter_id] = history
                if kwh_valid:
                    history["kwh"] = kwh
                    history["kwh_values"].append(kwh)
                if timestamp is not None:
                    history["timestamp"] = timestamp

        return pd.DataFrame(output, columns=self.feature_names, dtype=float).to_numpy()

    @classmethod
    def _reading_key(cls, record: Mapping[str, Any]) -> tuple[str, str] | None:
        meter_value = record.get("meter_id")
        timestamp = cls._timestamp(record.get("timestamp"))
        if cls._is_null(meter_value) or timestamp is None:
            return None
        return str(meter_value), timestamp.isoformat()

    @staticmethod
    def _records(X: Any) -> list[dict[str, Any]]:
        if isinstance(X, pd.DataFrame):
            return X.to_dict(orient="records")
        if isinstance(X, Mapping):
            return [dict(X)]
        if isinstance(X, Sequence) and not isinstance(X, (str, bytes)):
            records = list(X)
            if all(isinstance(record, Mapping) for record in records):
                return [dict(record) for record in records]
        raise TypeError("X must be a pandas DataFrame, a record mapping, or a sequence of mappings")

    @staticmethod
    def _is_null(value: Any) -> bool:
        return value is None or (pd.api.types.is_scalar(value) and bool(pd.isna(value)))

    @classmethod
    def _number(cls, record: Mapping[str, Any], field: str) -> tuple[float, bool]:
        if field not in record or cls._is_null(record[field]):
            return 0.0, False
        try:
            value = float(record[field])
        except (TypeError, ValueError, OverflowError):
            return 0.0, False
        return (value, True) if isfinite(value) else (0.0, False)

    @staticmethod
    def _timestamp(value: Any) -> Any:
        if AMIPayloadPreprocessor._is_null(value):
            return None
        timestamp = pd.to_datetime(value, utc=True, errors="coerce")
        return None if pd.isna(timestamp) else timestamp

    @classmethod
    def _malformed(cls, record: Mapping[str, Any], field: str, valid: bool) -> bool:
        return field in record and not cls._is_null(record[field]) and not valid
