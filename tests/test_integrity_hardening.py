"""Regression tests for source-data and request-boundary integrity."""

from datetime import timezone

import pytest
from fastapi import HTTPException

from backend.adapters import get_adapter
from backend.api import routes
from backend.db import database
from backend.main import app
from backend.models.canonical import CanonicalControlCommand, CanonicalMeterReading, CanonicalPayload
from backend.models.canonical import DiagnosticIssue, IssueSeverity
from backend.engine.scorer import ScoringEngine


def test_alpha_invalid_timestamp_is_rejected_without_fabricating_a_reading():
    adapter = get_adapter("alpha-hes")
    payload, issues = adapter.parse_to_canonical(
        {
            "meter_data": [
                {
                    "meter_number": "MTR-BAD-CLOCK",
                    "clock": "not-a-timestamp",
                    "registers": {"1.0.1.8.0.255": {"value": 12, "scaler": 0}},
                }
            ]
        }
    )

    assert payload.readings == []
    assert any(issue.code == "INVALID_TIMESTAMP_FORMAT" for issue in issues)


def test_alpha_accepts_epoch_zero_as_a_real_timestamp():
    adapter = get_adapter("alpha-hes")
    payload, issues = adapter.parse_to_canonical(
        {
            "meter_data": [
                {
                    "meter_number": "MTR-EPOCH",
                    "clock": 0,
                    "registers": {"1.0.1.8.0.255": {"value": 12, "scaler": 0}},
                }
            ]
        }
    )

    assert not issues
    assert payload.readings[0].timestamp.isoformat() == "1970-01-01T00:00:00+00:00"


def test_workbench_rejects_unknown_target_vendor():
    with database.SessionLocal() as db:
        with pytest.raises(HTTPException, match="Target vendor 'unknown-target' is not recognized"):
            routes._execute_workbench_payload(
                "delta-legacy",
                "unknown-target",
                '{"telemetry": []}',
                db,
            )


def test_public_models_default_to_timezone_aware_timestamps():
    payload = CanonicalPayload(source_system="alpha-hes")
    command = CanonicalControlCommand(meter_serial_number="MTR-1", action="DISCONNECT")

    assert payload.created_at.tzinfo is timezone.utc
    assert command.timestamp.tzinfo is timezone.utc


def test_cors_does_not_combine_wildcard_origins_with_credentials():
    cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")

    assert cors.kwargs["allow_credentials"] is False
    assert cors.kwargs["allow_origins"] != ["*"]


def test_upload_payload_rejects_content_larger_than_the_limit():
    with pytest.raises(HTTPException, match="Upload exceeds"):
        routes._ensure_payload_size(b"x" * (routes.MAX_UPLOAD_BYTES + 1))


def test_empty_dataset_is_incomplete_and_never_receives_a_compatibility_score():
    score = ScoringEngine.calculate_score(
        total_records=0,
        issues=[
            DiagnosticIssue(
                code="EMPTY_PAYLOAD",
                severity=IssueSeverity.WARNING,
                message="No readings.",
            )
        ],
    )

    assert score.grade == "INCOMPLETE"
    assert score.total_score == 0.0


def test_gamma_preserves_export_and_reactive_interval_blocks():
    adapter = get_adapter("gamma-mdms")
    payload, issues = adapter.parse_to_canonical(
        {
            "MeterReadingsMessage": {
                "MeterReadings": [
                    {
                        "EndDevice": {"mRID": "MTR-GAMMA"},
                        "IntervalBlocks": [
                            {"readingType": "ActiveEnergy.Import.kWh", "IntervalReadings": [{"timeStamp": "2026-01-01T00:00:00Z", "value": 10}]},
                            {"readingType": "ActiveEnergy.Export.kWh", "IntervalReadings": [{"timeStamp": "2026-01-01T00:00:00Z", "value": 2}]},
                            {"readingType": "ReactiveEnergy.kVArh", "IntervalReadings": [{"timeStamp": "2026-01-01T00:00:00Z", "value": 3}]},
                        ],
                    }
                ]
            }
        }
    )

    assert not issues
    reading = payload.readings[0]
    assert (reading.active_energy_import_kwh, reading.active_energy_export_kwh, reading.reactive_energy_kvarh) == (10.0, 2.0, 3.0)


def test_gamma_serialization_roundtrip_preserves_export_and_reactive_energy():
    adapter = get_adapter("gamma-mdms")
    original = CanonicalPayload(
        source_system="test",
        readings=[
            CanonicalMeterReading(
                meter_serial_number="MTR-GAMMA-RT",
                timestamp="2026-01-01T00:00:00Z",
                active_energy_import_kwh=10.0,
                active_energy_export_kwh=2.0,
                reactive_energy_kvarh=3.0,
            )
        ],
    )

    recovered, issues = adapter.parse_to_canonical(adapter.serialize_from_canonical(original))

    assert not issues
    reading = recovered.readings[0]
    assert (reading.active_energy_import_kwh, reading.active_energy_export_kwh, reading.reactive_energy_kvarh) == (10.0, 2.0, 3.0)


@pytest.mark.parametrize(
    ("vendor_id", "raw_payload", "code"),
    [
        ("beta-hes", "MTR_ID,RDG_TIME,KWH_IMP\nMTR-BETA,bad-time,12\n", "INVALID_CSV_TIMESTAMP"),
        ("gamma-mdms", {"MeterReadingsMessage": {"MeterReadings": [{"EndDevice": {"mRID": "MTR-GAMMA-BAD"}, "IntervalBlocks": [{"readingType": "ActiveEnergy.Import.kWh", "IntervalReadings": [{"timeStamp": "bad-time", "value": 12}]}]}]}}, "INVALID_CIM_TIMESTAMP"),
        ("delta-legacy", {"telemetry": [{"device_uid": "MTR-DELTA-BAD", "timestamp": "bad-time", "act_wh": 12000}]}, "INVALID_TIMESTAMP_FORMAT"),
    ],
)
def test_adapters_reject_invalid_timestamps_without_creating_readings(vendor_id, raw_payload, code):
    payload, issues = get_adapter(vendor_id).parse_to_canonical(raw_payload)

    assert payload.readings == []
    assert any(issue.code == code for issue in issues)
