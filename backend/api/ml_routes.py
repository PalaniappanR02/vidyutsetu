"""ML inference endpoints for canonical AMI readings."""

from datetime import datetime
from typing import Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.ml.inference import (
    MLArtifactsError,
    get_ml_health,
    make_ml_findings,
    predict_canonical_readings,
)

router = APIRouter(prefix="/ml", tags=["ML"])

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


@router.get("/health")
def ml_health():
    try:
        return get_ml_health()
    except MLArtifactsError as error:
        raise _unavailable(error) from error


@router.post("/validate")
def validate_reading(reading: CanonicalReadingInput):
    try:
        predictions = predict_canonical_readings(
            [reading.model_dump(mode="json", exclude_unset=True)]
        )
        is_synthetic = get_ml_health()["is_synthetic"]
    except MLArtifactsError as error:
        raise _unavailable(error) from error
    return {
        "prediction": predictions[0],
        "findings": make_ml_findings(predictions),
        "is_synthetic": is_synthetic,
    }


@router.post("/validate-batch")
def validate_reading_batch(batch: BatchValidationInput):
    try:
        predictions = predict_canonical_readings(
            [reading.model_dump(mode="json", exclude_unset=True) for reading in batch.readings]
        )
        is_synthetic = get_ml_health()["is_synthetic"]
    except MLArtifactsError as error:
        raise _unavailable(error) from error
    return {
        "predictions": predictions,
        "findings": make_ml_findings(predictions),
        "is_synthetic": is_synthetic,
    }
