"""ML inference endpoints for canonical AMI readings."""

from datetime import datetime
import json
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.db.database import DBMeterHistory, get_db
from app.ml.inference import (
    MLArtifactsError,
    get_ml_health,
    make_ml_findings,
    predict_canonical_readings,
)

router = APIRouter(prefix="/ml", tags=["ml"])

NumericInput = Union[float, str, None]
TimestampInput = Union[datetime, str, None]


class CanonicalReadingInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    meter_serial_number: Union[str, None] = None
    timestamp: TimestampInput = None
    interval_minutes: NumericInput = None
    active_energy_import_kwh: NumericInput = None
    active_energy_export_kwh: NumericInput = None
    reactive_energy_kvarh: NumericInput = None
    apparent_energy_kvah: NumericInput = None
    voltage_v: NumericInput = None
    current_a: NumericInput = None
    power_factor: NumericInput = None
    frequency_hz: NumericInput = None


class BatchValidationInput(BaseModel):
    readings: list[CanonicalReadingInput]


def _unavailable(error: MLArtifactsError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


def _validate_with_meter_history(
    readings: list[CanonicalReadingInput],
    db: Session,
) -> list[dict[str, Any]]:
    submitted = [reading.model_dump(mode="json", exclude_unset=True) for reading in readings]
    meter_ids = {
        payload["meter_serial_number"]
        for payload in submitted
        if payload.get("meter_serial_number")
    }

    history_rows: list[DBMeterHistory] = []
    for meter_id in meter_ids:
        history_rows.extend(
            db.query(DBMeterHistory)
            .filter(DBMeterHistory.meter_id == meter_id)
            .order_by(DBMeterHistory.id.desc())
            .limit(50)
            .all()
        )
    history_rows.sort(key=lambda row: row.id)
    history = [json.loads(row.payload_json) for row in history_rows]

    predictions = predict_canonical_readings(history + submitted)
    new_predictions = predictions[len(history):]
    for index, prediction in enumerate(new_predictions):
        prediction["reading_index"] = index

    for payload in submitted:
        meter_id = payload.get("meter_serial_number")
        if not meter_id:
            continue
        db.add(
            DBMeterHistory(
                meter_id=meter_id,
                ts=str(payload.get("timestamp") or ""),
                payload_json=json.dumps(payload, separators=(",", ":"), default=str),
            )
        )
    db.flush()
    for meter_id in meter_ids:
        stale_rows = (
            db.query(DBMeterHistory)
            .filter(DBMeterHistory.meter_id == meter_id)
            .order_by(DBMeterHistory.id.desc())
            .offset(50)
            .all()
        )
        for stale_row in stale_rows:
            db.delete(stale_row)
    db.commit()
    return new_predictions


@router.get("/health")
def ml_health():
    try:
        return get_ml_health()
    except MLArtifactsError as error:
        raise _unavailable(error) from error


@router.post("/validate")
def validate_reading(reading: CanonicalReadingInput, db: Session = Depends(get_db)):
    try:
        predictions = _validate_with_meter_history([reading], db)
        is_synthetic = get_ml_health()["is_synthetic"]
    except MLArtifactsError as error:
        raise _unavailable(error) from error
    return {
        "prediction": predictions[0],
        "findings": make_ml_findings(predictions),
        "is_synthetic": is_synthetic,
    }


@router.post("/validate-batch")
def validate_reading_batch(batch: BatchValidationInput, db: Session = Depends(get_db)):
    try:
        predictions = _validate_with_meter_history(batch.readings, db)
        is_synthetic = get_ml_health()["is_synthetic"]
    except MLArtifactsError as error:
        raise _unavailable(error) from error
    return {
        "predictions": predictions,
        "findings": make_ml_findings(predictions),
        "is_synthetic": is_synthetic,
    }
