"""Canonical Data Model (CDM) for VidyutSetu AMI Interoperability Testing Workbench.
Aligned with IEC 61968-9, DLMS/COSEM (IEC 62056), and IS 15959.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
import uuid


class QualityCode(str, Enum):
    VALID = "VALID"
    ESTIMATED = "ESTIMATED"
    SUSPECT = "SUSPECT"
    MALFORMED = "MALFORMED"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class EventSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    WARNING = "WARNING"
    INFO = "INFO"


class EventCode(str, Enum):
    TAMPER_MAGNETIC = "TAMPER_MAGNETIC"
    TAMPER_COVER_OPEN = "TAMPER_COVER_OPEN"
    POWER_OUTAGE = "POWER_OUTAGE"
    POWER_RESTORED = "POWER_RESTORED"
    VOLTAGE_SAG = "VOLTAGE_SAG"
    VOLTAGE_SWELL = "VOLTAGE_SWELL"
    REVERSE_CURRENT = "REVERSE_CURRENT"
    NEUTRAL_DISTURBANCE = "NEUTRAL_DISTURBANCE"
    METER_CLOCK_DRIFT = "METER_CLOCK_DRIFT"
    COMMUNICATION_FAILURE = "COMMUNICATION_FAILURE"
    FIRMWARE_UPGRADED = "FIRMWARE_UPGRADED"
    OTHER_EVENT = "OTHER_EVENT"


class ControlAction(str, Enum):
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"
    LIMIT_LOAD = "LIMIT_LOAD"
    ARM_FOR_RECONNECT = "ARM_FOR_RECONNECT"


class ControlStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class CanonicalMeterReading(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meter_serial_number: str = Field(..., description="Alphanumeric unique meter identifier")
    timestamp: datetime = Field(..., description="ISO 8601 UTC timestamp of reading")
    interval_minutes: int = Field(default=15, description="Interval block length in minutes (e.g. 15, 30, 60)")
    active_energy_import_kwh: float = Field(..., description="Cumulative Active Energy Import in kWh")
    active_energy_export_kwh: Optional[float] = Field(default=0.0, description="Cumulative Active Energy Export in kWh")
    reactive_energy_kvarh: Optional[float] = Field(default=0.0, description="Cumulative Reactive Energy in kVArh")
    apparent_energy_kvah: Optional[float] = Field(default=None, description="Cumulative Apparent Energy in kVAh")
    voltage_v: Optional[float] = Field(default=None, description="Instantaneous RMS Voltage in Volts (Phase-Neutral or L1)")
    current_a: Optional[float] = Field(default=None, description="Instantaneous RMS Current in Amperes (Phase L1)")
    power_factor: Optional[float] = Field(default=None, description="Power factor between -1.0 and 1.0")
    frequency_hz: Optional[float] = Field(default=50.0, description="Instantaneous grid frequency in Hz")
    quality_code: QualityCode = Field(default=QualityCode.VALID, description="Data conformance quality status")
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Vendor-specific original context")


class CanonicalMeterEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meter_serial_number: str = Field(..., description="Target meter serial number")
    event_code: EventCode = Field(..., description="Standardized event code")
    timestamp: datetime = Field(..., description="UTC timestamp of event occurrence")
    severity: EventSeverity = Field(default=EventSeverity.WARNING)
    raw_vendor_code: Optional[str] = Field(default=None, description="Original vendor alarm string/code")
    description: Optional[str] = Field(default=None, description="Human readable description")
    details: Dict[str, Any] = Field(default_factory=dict)


class CanonicalControlCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meter_serial_number: str = Field(..., description="Target meter serial number")
    action: ControlAction = Field(..., description="Requested control action")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    parameter_value: Optional[float] = Field(default=None, description="Optional parameter e.g. kW limit")
    status: ControlStatus = Field(default=ControlStatus.PENDING)
    response_code: Optional[str] = None
    response_message: Optional[str] = None


class CanonicalPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_system: str = Field(..., description="ID or name of origin system / HES")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    version: str = Field(default="1.0.0")
    readings: List[CanonicalMeterReading] = Field(default_factory=list)
    events: List[CanonicalMeterEvent] = Field(default_factory=list)
    controls: List[CanonicalControlCommand] = Field(default_factory=list)


# Diagnostics & Test Result Models

class IssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class DiagnosticIssue(BaseModel):
    code: str = Field(..., description="Issue code e.g. INVALID_TIMESTAMP, MISSING_REQUIRED_FIELD")
    field: Optional[str] = Field(default=None, description="Affected field path")
    severity: IssueSeverity = Field(default=IssueSeverity.ERROR)
    message: str = Field(..., description="Clear explanation of the problem")
    observed_value: Any = Field(default=None)
    expected_format: Optional[str] = Field(default=None)
    suggested_fix: Optional[str] = Field(default=None, description="Actionable recommendation or mapping override")


class CompatibilityScoreBreakdown(BaseModel):
    syntactic_score: float = Field(..., description="0-100: Format, syntax, parsing integrity")
    semantic_score: float = Field(..., description="0-100: Standard units, OBIS mappings, valid types")
    data_integrity_score: float = Field(..., description="0-100: Monotonicity, electrical sanity, timestamps")
    total_score: float = Field(..., description="Weighted composite score 0-100")
    grade: str = Field(..., description="A+ (>=95), A (>=85), B (>=70), C (>=50), F (<50)")
    summary: str = Field(..., description="High-level interoperability judgment")


class TestExecutionReport(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_time: datetime = Field(default_factory=datetime.utcnow)
    source_vendor: str
    target_vendor: Optional[str] = None
    total_records_processed: int = 0
    valid_records_count: int = 0
    invalid_records_count: int = 0
    issues: List[DiagnosticIssue] = Field(default_factory=list)
    score: CompatibilityScoreBreakdown
    transformation_applied: bool = False
    duration_ms: float = 0.0
