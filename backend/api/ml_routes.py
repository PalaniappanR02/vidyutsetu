"""ML inference endpoints for canonical AMI readings."""

from datetime import datetime
import json
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.engine.history_analytics import build_meter_profile
from backend.db.database import DBMeterHistory, get_db
from app.ml.inference import (
    MLArtifactsError,
    explain_canonical_readings,
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


class ExplanationInput(BaseModel):
    readings: list[CanonicalReadingInput] = Field(..., min_length=1)


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


@router.get("/meters")
def list_meters_with_history(db: Session = Depends(get_db)):
    """Meters that currently have stored readings, newest arrival first."""
    counts = dict(
        db.query(DBMeterHistory.meter_id, func.count(DBMeterHistory.id))
        .group_by(DBMeterHistory.meter_id)
        .all()
    )
    if not counts:
        return []
    latest_ids = dict(
        db.query(DBMeterHistory.meter_id, func.max(DBMeterHistory.id))
        .group_by(DBMeterHistory.meter_id)
        .all()
    )
    latest_rows = {
        row.meter_id: row
        for row in db.query(DBMeterHistory)
        .filter(DBMeterHistory.id.in_(list(latest_ids.values())))
        .all()
    }
    meters = []
    for meter_id, count in counts.items():
        row = latest_rows.get(meter_id)
        meters.append(
            {
                "meter_id": meter_id,
                "reading_count": count,
                "last_arrival_id": row.id if row else None,
                "last_ts": row.ts if row else None,
            }
        )
    meters.sort(key=lambda item: item["last_arrival_id"] or 0, reverse=True)
    return meters


@router.get("/meters/{meter_id}/profile")
def meter_profile(meter_id: str, db: Session = Depends(get_db)):
    """Behaviour profile and arrival-order drift for one meter's stored history."""
    rows = (
        db.query(DBMeterHistory)
        .filter(DBMeterHistory.meter_id == meter_id)
        .order_by(DBMeterHistory.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No stored history for meter '{meter_id}'. Submit readings to "
                "/ml/validate or /ml/validate-batch first."
            ),
        )
    payloads = [json.loads(row.payload_json) for row in rows]
    return build_meter_profile(
        meter_id,
        payloads,
        first_arrival_id=rows[0].id,
        last_arrival_id=rows[-1].id,
    )


@router.post("/explain")
def explain_reading_batch(batch: ExplanationInput):
    """SHAP feature contributions from the saved classifier (no retraining)."""
    try:
        explanations = explain_canonical_readings(batch.readings)
        is_synthetic = get_ml_health()["is_synthetic"]
    except MLArtifactsError as error:
        raise _unavailable(error) from error
    return {
        "method": "shap_tree_explainer",
        "explanations": explanations,
        "is_synthetic": is_synthetic,
    }
