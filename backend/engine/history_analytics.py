"""Meter behaviour profiling and drift detection over stored ``meter_history`` rows.

Everything here is computed from readings that were actually submitted and stored
by ``/ml/validate`` / ``/ml/validate-batch``. Windows follow *arrival order* (the
order rows were stored), never timestamp order, matching the ML sequence
contract. All output is rule-derived: ``source: "rule"``.
"""

from __future__ import annotations

from math import isfinite
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

#: Drift is flagged when the recent-window mean moves past these documented limits.
DRIFT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "energy_kwh": {"kind": "relative", "value": 0.10, "unit": "fraction_of_baseline_mean"},
    "voltage_v": {"kind": "absolute", "value": 5.0, "unit": "V"},
    "power_factor": {"kind": "absolute", "value": 0.05, "unit": "pf"},
    "frequency_hz": {"kind": "absolute", "value": 0.2, "unit": "Hz"},
}

PROFILE_METRICS: dict[str, str] = {
    "energy_kwh": "active_energy_import_kwh",
    "voltage_v": "voltage_v",
    "power_factor": "power_factor",
    "frequency_hz": "frequency_hz",
}


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _series(payloads: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for payload in payloads:
        number = _to_float(payload.get(key))
        if number is not None:
            values.append(number)
    return values


def _stats(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(fmean(values), 4),
    }


def _drift_for_metric(
    baseline: Sequence[float],
    recent: Sequence[float],
    threshold: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not baseline or not recent:
        return None
    baseline_mean = fmean(baseline)
    recent_mean = fmean(recent)
    delta = recent_mean - baseline_mean
    if threshold["kind"] == "relative":
        baseline_reference = abs(baseline_mean) if baseline_mean else 0.0
        exceeds = baseline_reference > 0 and abs(delta) / baseline_reference >= threshold["value"]
    else:
        exceeds = abs(delta) >= threshold["value"]
    if abs(delta) < 1e-9:
        direction = "stable"
    else:
        direction = "increase" if delta > 0 else "decrease"
    return {
        "baseline_mean": round(baseline_mean, 4),
        "recent_mean": round(recent_mean, 4),
        "delta": round(delta, 4),
        "direction": direction,
        "exceeds_threshold": bool(exceeds),
        "threshold": dict(threshold),
    }


def compute_drift(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare the older and newer halves of the stored window (arrival order)."""
    window_size = len(payloads) // 2
    drift: dict[str, Any] = {
        "basis": "stored_history_arrival_order",
        "window_size": window_size,
        "readings_used": len(payloads),
        "thresholds": DRIFT_THRESHOLDS,
        "metrics": {},
    }
    if window_size == 0:
        drift["available"] = False
        drift["note"] = "At least two stored readings are required to compare windows."
        for metric in PROFILE_METRICS:
            drift[metric] = None
        return drift

    baseline_window = payloads[:window_size]
    recent_window = payloads[-window_size:]
    drift["available"] = True
    for metric, field in PROFILE_METRICS.items():
        metric_drift = _drift_for_metric(
            _series(baseline_window, field),
            _series(recent_window, field),
            DRIFT_THRESHOLDS[metric],
        )
        drift["metrics"][metric] = metric_drift
        drift[metric] = metric_drift
    drift["flagged_metrics"] = sorted(
        metric
        for metric, metric_drift in drift["metrics"].items()
        if metric_drift and metric_drift["exceeds_threshold"]
    )
    return drift


def build_meter_profile(
    meter_id: str,
    payloads: Sequence[Mapping[str, Any]],
    *,
    first_arrival_id: int | None = None,
    last_arrival_id: int | None = None,
) -> dict[str, Any]:
    """Summarize stored readings for one meter, oldest arrival first."""
    profile: dict[str, Any] = {
        "meter_id": meter_id,
        "readings_used": len(payloads),
        "arrival_order": True,
        "first_arrival_id": first_arrival_id,
        "last_arrival_id": last_arrival_id,
        "source": "rule",
        "notes": [
            "Computed only from readings stored by /ml/validate and /ml/validate-batch.",
            "Windows follow arrival order, not timestamp order.",
            "Profile is descriptive statistics; it is not a conformance verdict.",
        ],
    }
    for metric, field in PROFILE_METRICS.items():
        profile[metric] = _stats(_series(payloads, field))
    profile["drift"] = compute_drift(payloads)
    return profile
