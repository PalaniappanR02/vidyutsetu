"""Batch A: every test gets its own SQLite database, so meter history never leaks."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api import ml_routes
from backend.db import database
from backend.db.database import DBMeterHistory
from backend.main import app

client = TestClient(app)

# Deliberately fixed: the second test reuses the exact id the first test stored.
SHARED_METER_ID = "MTR-ISOLATION-SHARED"


@pytest.fixture
def fake_predict(monkeypatch):
    observed = []

    def _predict(readings):
        observed.append(readings)
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
    return observed


def _reading(meter_id: str, kwh: float = 12.0) -> dict:
    return {
        "meter_serial_number": meter_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "active_energy_import_kwh": kwh,
    }


def test_first_test_stores_history_for_the_shared_meter(fake_predict):
    response = client.post("/ml/validate", json=_reading(SHARED_METER_ID))

    assert response.status_code == 200
    with database.SessionLocal() as db:
        rows = db.query(DBMeterHistory).filter(DBMeterHistory.meter_id == SHARED_METER_ID).all()
    assert len(rows) == 1


def test_second_test_starts_with_empty_history_and_scores_only_the_new_reading(fake_predict):
    with database.SessionLocal() as db:
        rows = db.query(DBMeterHistory).filter(DBMeterHistory.meter_id == SHARED_METER_ID).all()
    assert rows == []

    response = client.post("/ml/validate", json=_reading(SHARED_METER_ID, 13.0))

    assert response.status_code == 200
    assert len(fake_predict[0]) == 1


def test_unrelated_tables_are_empty_at_the_start_of_each_test():
    with database.SessionLocal() as db:
        assert db.query(DBMeterHistory).count() == 0


def test_unique_meter_ids_still_accumulate_history_inside_one_test(fake_predict):
    meter_id = f"MTR-ISO-{uuid.uuid4().hex}"

    first = client.post("/ml/validate", json=_reading(meter_id, 10.0))
    second = client.post("/ml/validate", json=_reading(meter_id, 11.0))

    assert first.status_code == second.status_code == 200
    assert len(fake_predict[0]) == 1
    assert len(fake_predict[1]) == 2
    with database.SessionLocal() as db:
        assert db.query(DBMeterHistory).filter(DBMeterHistory.meter_id == meter_id).count() == 2
