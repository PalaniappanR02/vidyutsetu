"""Directed cross-vendor roundtrip semantic preservation tests.

For every ordered pair of distinct vendors (12 combinations) we run
source -> canonical -> target -> canonical and assert that the semantic
values survive (meter identity, timestamp instant, energy, voltage,
current, power factor, frequency, events) rather than comparing raw JSON.
"""

from datetime import timezone

import pytest

from backend.adapters import get_adapter
from backend.models.canonical import CanonicalPayload


ALPHA_PAYLOAD = {
    "system_id": "alpha-hes",
    "meter_data": [
        {
            "meter_number": "SM-RT-001",
            "clock": "2026-03-31T14:00:00Z",
            "interval_minutes": 15,
            "registers": {
                "1.0.1.8.0.255": {"value": 150000, "scaler": -3, "unit": "kWh"},
                "1.0.2.8.0.255": {"value": 5000, "scaler": -3, "unit": "kWh"},
                "1.0.3.8.0.255": {"value": 1000, "scaler": -3, "unit": "kVArh"},
                "1.0.12.7.0.255": {"value": 2350, "scaler": -1, "unit": "V"},
                "1.0.11.7.0.255": {"value": 520, "scaler": -2, "unit": "A"},
                "1.0.13.7.0.255": {"value": 95, "scaler": -2, "unit": ""},
                "1.0.14.7.0.255": {"value": 5000, "scaler": -2, "unit": "Hz"},
            },
            "events": [
                {"code": "EVT_DLMS_TAMPER_MAG", "timestamp": "2026-03-31T14:00:00Z", "description": "mag tamper"}
            ],
        }
    ],
}

BETA_PAYLOAD = (
    "MTR_ID,RDG_TIME,KWH_IMP,KWH_EXP,KVARH_LAG,VRMS,IRMS,PF,FREQ,ALARM_CODE\n"
    "SM-RT-002,31-03-2026 19:30:00,150.0000,5.0000,1.0000,235.00,5.200,0.950,50.00,MAG_TAMPER\n"
)

GAMMA_PAYLOAD = {
    "MeterReadingsMessage": {
        "MeterReadings": [
            {
                "EndDevice": {"mRID": "SM-RT-003"},
                "IntervalBlocks": [
                    {"readingType": "IEC61968-9.ActiveEnergy.Import.kWh", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 150.0}]},
                    {"readingType": "IEC61968-9.ActiveEnergy.Export.kWh", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 5.0}]},
                    {"readingType": "IEC61968-9.ReactiveEnergy.kVArh", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 1.0}]},
                    {"readingType": "IEC61968-9.Voltage.RMS.V", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 235.0}]},
                    {"readingType": "IEC61968-9.Current.RMS.A", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 5.2}]},
                    {"readingType": "IEC61968-9.PowerFactor", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 0.95}]},
                    {"readingType": "IEC61968-9.Frequency.Hz", "IntervalReadings": [{"timeStamp": "2026-03-31T14:00:00Z", "value": 50.0}]},
                ],
            }
        ],
        "EndDeviceEvents": [
            {"EndDevice": {"mRID": "SM-RT-003"}, "EndDeviceEventType": "CIM.ENDDEVICE.TAMPER.MAGNET", "createdDateTime": "2026-03-31T14:00:00Z", "description": "mag tamper"}
        ],
    }
}

DELTA_PAYLOAD = {
    "telemetry": [
        {
            "device_uid": "SM-RT-004",
            "timestamp": "2026-03-31T14:00:00Z",
            "act_wh": 150000,
            "exp_wh": 5000,
            "volt_mv": 235000,
            "curr_ma": 5200,
            "p_fact_pct": 95,
            "freq_hz": 50.0,
            "alarm_tag": "TAMPER_MAG",
        }
    ]
}

SOURCE_PAYLOADS = {
    "alpha-hes": ALPHA_PAYLOAD,
    "beta-hes": BETA_PAYLOAD,
    "gamma-mdms": GAMMA_PAYLOAD,
    "delta-legacy": DELTA_PAYLOAD,
}

VENDORS = ["alpha-hes", "beta-hes", "gamma-mdms", "delta-legacy"]


def _tol(a, b, tol):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


@pytest.mark.parametrize("source", VENDORS)
@pytest.mark.parametrize("target", VENDORS)
def test_directed_roundtrip_semantic_preservation(source, target):
    if source == target:
        pytest.skip("same-vendor roundtrip covered elsewhere")

    src_adapter = get_adapter(source)
    tgt_adapter = get_adapter(target)
    assert src_adapter is not None and tgt_adapter is not None

    original_payload = SOURCE_PAYLOADS[source]
    canonical_before, src_issues = src_adapter.parse_to_canonical(original_payload)
    assert canonical_before.readings, f"source {source} produced no readings: {src_issues}"

    target_output = tgt_adapter.serialize_from_canonical(canonical_before)
    canonical_after, tgt_issues = tgt_adapter.parse_to_canonical(target_output)
    assert canonical_after.readings, f"target {target} produced no readings: {tgt_issues}"

    assert len(canonical_before.readings) == len(canonical_after.readings), (
        f"{source}->{target}: reading count {len(canonical_before.readings)} vs {len(canonical_after.readings)}"
    )

    for before, after in zip(canonical_before.readings, canonical_after.readings):
        assert before.meter_serial_number == after.meter_serial_number, f"{source}->{target} meter id changed"
        assert abs((before.timestamp - after.timestamp).total_seconds()) < 1.0, (
            f"{source}->{target} timestamp changed: {before.timestamp} vs {after.timestamp}"
        )
        assert _tol(before.active_energy_import_kwh, after.active_energy_import_kwh, 1e-3), (
            f"{source}->{target} import energy: {before.active_energy_import_kwh} vs {after.active_energy_import_kwh}"
        )
        assert _tol(before.active_energy_export_kwh, after.active_energy_export_kwh, 1e-3)
        assert _tol(before.reactive_energy_kvarh, after.reactive_energy_kvarh, 1e-3)
        assert _tol(before.voltage_v, after.voltage_v, 1e-2)
        assert _tol(before.current_a, after.current_a, 1e-3)
        assert _tol(before.power_factor, after.power_factor, 1e-3)
        assert _tol(before.frequency_hz, after.frequency_hz, 1e-2)

    # Events: compare code multisets when both sides carry them.
    before_codes = sorted(e.event_code.value for e in canonical_before.events)
    after_codes = sorted(e.event_code.value for e in canonical_after.events)
    if before_codes:
        assert after_codes == before_codes, (
            f"{source}->{target} events changed: {before_codes} vs {after_codes}"
        )
