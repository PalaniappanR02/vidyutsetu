"""REST API Routes for VidyutSetu Workbench."""

import json
import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.db.database import (
    get_db,
    DBTestRun,
    DBCustomVendorConfig,
    DBTestSuite,
    DBSuiteRun,
)
from backend.security.auth import require_roles
from backend.adapters.registry import get_adapter, list_registered_vendors
from backend.engine.validator import ValidationEngine
from backend.engine.scorer import ScoringEngine, DiagnosticSuggester
from backend.engine.report_builder import build_run_report
from backend.generator.simulator import SyntheticAmiGenerator
from backend.config import settings
from backend.models.canonical import (
    CanonicalPayload,
    DiagnosticIssue,
    TestExecutionReport,
    CompatibilityScoreBreakdown
)
from backend.models.vendor import VendorProfile
from app.ml.inference import (
    MLArtifactsError,
    get_ml_health,
    make_ml_findings,
    predict_canonical_readings,
)

router = APIRouter()
LOGGER = logging.getLogger("vidyutsetu.api")
workbench_router = APIRouter(prefix="/api", tags=["workbench"])
compare_router = APIRouter(prefix="/api", tags=["compare"])
roundtrip_router = APIRouter(prefix="/api", tags=["roundtrip"])
suites_router = APIRouter(prefix="/api", tags=["suites"])

PARSE_DIAGNOSTIC_CODES = {
    "JSON_PARSE_ERROR",
    "CSV_PARSE_FAILED",
    "UNSUPPORTED_DATA_TYPE",
    "INVALID_CSV_INPUT",
}
MAX_UPLOAD_BYTES = settings.max_request_bytes
SEMANTIC_DIAGNOSTIC_CODES = {
    "MISSING_ACTIVE_IMPORT_ENERGY",
    "MISSING_ACT_WH",
    "MISSING_CIM_ACTIVE_ENERGY",
    "MISSING_METER_ID",
    "MISSING_DEVICE_UID",
    "EMPTY_METER_ID",
    "NUMBER_COERCION_ERROR",
    "INVALID_TIMESTAMP_FORMAT",
    "INVALID_CSV_TIMESTAMP",
    "INVALID_CIM_TIMESTAMP",
}
PHYSICAL_DIAGNOSTIC_CODES = {
    "NEGATIVE_ACTIVE_ENERGY",
    "VOLTAGE_NEAR_ZERO",
    "VOLTAGE_OUT_OF_BOUNDS",
    "NEGATIVE_CURRENT",
    "OVERCURRENT_ALARM",
    "POWER_FACTOR_OUT_OF_RANGE",
    "GRID_FREQUENCY_ABNORMAL",
    "FUTURE_TIMESTAMP",
    "EXCESSIVE_CLOCK_DRIFT",
    "NON_MONOTONIC_ENERGY_REGISTER",
    "DUPLICATE_INTERVAL_TIMESTAMP",
}


class CompareRunsInput(BaseModel):
    baseline_run_id: str
    candidate_run_id: str


class RoundTripInput(BaseModel):
    vendor_a: str
    vendor_b: str
    payload: Any


class SuiteCreateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scenarios: List[Dict[str, Any]] = Field(..., max_length=100)


def _stage(
    name: str,
    diagnostics: List[Dict[str, Any]],
    duration_ms: float,
    *,
    skipped: bool = False,
) -> Dict[str, Any]:
    if skipped:
        status = "skipped"
    elif any(item.get("severity") == "ERROR" for item in diagnostics):
        status = "fail"
    elif diagnostics:
        status = "warn"
    else:
        status = "pass"
    first = diagnostics[0] if diagnostics else {}
    return {
        "name": name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "diagnostics": diagnostics,
        "root_cause": first.get("message"),
        "suggested_action": first.get("suggested_fix"),
    }


def _ml_model_version() -> Optional[str]:
    """Version tag read from the existing artifacts (no retraining, no new files)."""
    try:
        health = get_ml_health()
    except MLArtifactsError:
        return None
    classifier = health["model_versions"]["fault_classifier"][:12]
    detector = health["model_versions"]["anomaly_detector"][:8]
    algorithm = health["metrics"].get("selected_classifier", "classifier")
    return f"{algorithm}-{classifier}+iforest-{detector}"


def _execute_workbench_payload(
    source_vendor: str,
    target_vendor: Optional[str],
    content_str: str,
    db: Session,
) -> Dict[str, Any]:
    _ensure_payload_size(content_str.encode("utf-8", errors="replace"))
    start_time = time.time()
    source_adapter = get_adapter(source_vendor)
    if not source_adapter:
        raise HTTPException(
            status_code=400,
            detail=f"Source vendor '{source_vendor}' is not recognized.",
        )

    parse_started = time.perf_counter()
    parsing_succeeded = True
    parsed_input: Any = content_str
    if source_adapter.profile.format_type == "json":
        try:
            parsed_input = json.loads(content_str)
        except Exception:
            parsing_succeeded = False

    canonical_payload, adapter_issues = source_adapter.parse_to_canonical(parsed_input)
    parse_duration_ms = (time.perf_counter() - parse_started) * 1000.0
    parse_issues = [
        issue for issue in adapter_issues if issue.code in PARSE_DIAGNOSTIC_CODES
    ]
    semantic_adapter_issues = [
        issue for issue in adapter_issues if issue.code in SEMANTIC_DIAGNOSTIC_CODES
    ]
    syntactic_issues = [
        issue
        for issue in adapter_issues
        if issue not in parse_issues and issue not in semantic_adapter_issues
    ]

    syntax_started = time.perf_counter()
    syntactic_diagnostics = [issue.model_dump() for issue in syntactic_issues]
    syntactic_duration_ms = (time.perf_counter() - syntax_started) * 1000.0

    validation_started = time.perf_counter()
    validation_issues, valid_count, invalid_count = (
        ValidationEngine.validate_canonical_payload(canonical_payload)
    )
    validation_duration_ms = (time.perf_counter() - validation_started) * 1000.0
    all_issues = adapter_issues + validation_issues
    all_issues = DiagnosticSuggester.enrich_issues_with_remediation(all_issues)

    total_records = len(canonical_payload.readings)
    score_breakdown = ScoringEngine.calculate_score(
        total_records=total_records,
        issues=all_issues,
        format_parsed_successfully=parsing_succeeded,
    )

    ml_started = time.perf_counter()
    ml_error = None
    try:
        ml_results = predict_canonical_readings(canonical_payload.readings)
    except MLArtifactsError as error:
        ml_results = []
        ml_error = str(error)
    ml_findings = make_ml_findings(ml_results)
    ml_diagnostics = [dict(finding) for finding in ml_findings]
    if ml_error:
        ml_diagnostics.append(
            {
                "code": "ML_SCREENING_UNAVAILABLE",
                "severity": "WARNING",
                "message": ml_error,
                "source": "ml",
            }
        )
    ml_duration_ms = (time.perf_counter() - ml_started) * 1000.0

    target_output = None
    if target_vendor and target_vendor != "none":
        target_adapter = get_adapter(target_vendor)
        if not target_adapter:
            raise HTTPException(
                status_code=400,
                detail=f"Target vendor '{target_vendor}' is not recognized.",
            )
        target_output = target_adapter.serialize_from_canonical(canonical_payload)

    parse_diagnostics = [issue.model_dump() for issue in parse_issues]
    if not parsing_succeeded and not parse_diagnostics:
        parse_diagnostics.append(
            {
                "code": "JSON_PARSE_ERROR",
                "severity": "ERROR",
                "message": "Input could not be parsed as JSON.",
            }
        )
    semantic_started = time.perf_counter()
    semantic_diagnostics = [
        issue.model_dump() for issue in semantic_adapter_issues
    ] + [
        issue.model_dump()
        for issue in validation_issues
        if issue.code not in PHYSICAL_DIAGNOSTIC_CODES
    ]
    semantic_duration_ms = (time.perf_counter() - semantic_started) * 1000.0
    physical_diagnostics = [
        issue.model_dump()
        for issue in validation_issues
        if issue.code in PHYSICAL_DIAGNOSTIC_CODES
    ]
    stages = [
        _stage("parse", parse_diagnostics, parse_duration_ms),
        _stage("syntactic", syntactic_diagnostics, syntactic_duration_ms),
        _stage("semantic mapping", semantic_diagnostics, semantic_duration_ms),
        _stage("physical sanity", physical_diagnostics, validation_duration_ms),
        _stage("ML screening", ml_diagnostics, ml_duration_ms, skipped=bool(ml_error)),
    ]

    data_quality = ScoringEngine.calculate_data_quality(
        total_records=total_records,
        valid_records=valid_count,
        issues=all_issues,
    )
    model_version = _ml_model_version()

    findings = [
        {
            **issue.model_dump(),
            "source": "rule",
            "confidence": 1.0,
            "confidence_source": "deterministic_rule",
            "explanation": issue.message,
        }
        for issue in all_issues
    ] + ml_findings
    elapsed_ms = round((time.time() - start_time) * 1000.0, 2)
    run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
    db_run = DBTestRun(
        run_id=run_id,
        execution_time=datetime.now(timezone.utc),
        source_vendor=source_vendor,
        target_vendor=target_vendor,
        total_records=total_records,
        valid_records=valid_count,
        invalid_records=invalid_count,
        syntactic_score=score_breakdown.syntactic_score,
        semantic_score=score_breakdown.semantic_score,
        integrity_score=score_breakdown.data_integrity_score,
        total_score=score_breakdown.total_score,
        grade=score_breakdown.grade,
        summary=score_breakdown.summary,
        issues_json=json.dumps([issue.model_dump() for issue in all_issues]),
        raw_preview=content_str[:5000],
        canonical_preview=json.dumps(canonical_payload.model_dump(), default=str)[:10000],
        target_preview=(
            json.dumps(target_output, default=str)[:10000]
            if isinstance(target_output, (dict, list))
            else (str(target_output)[:10000] if target_output else "")
        ),
        duration_ms=elapsed_ms,
        model_version=model_version,
        data_quality_score=data_quality["score"],
    )
    db.add(db_run)
    db.commit()

    return {
        "run_id": run_id,
        "execution_time": datetime.now(timezone.utc).isoformat(),
        "source_vendor": source_vendor,
        "target_vendor": target_vendor,
        "total_records": total_records,
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "score": score_breakdown.model_dump(),
        "conformance_outcome": score_breakdown.grade,
        "issues": [issue.model_dump() for issue in all_issues],
        "findings": findings,
        "ml_results": ml_results,
        "ml_findings": ml_findings,
        "ml_error": ml_error,
        "canonical_payload": canonical_payload.model_dump(),
        "target_output": target_output,
        "duration_ms": elapsed_ms,
        "stages": stages,
        "model_version": model_version,
        "data_quality": data_quality,
    }

@workbench_router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "VidyutSetu AMI Interoperability Workbench",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }


@workbench_router.get(
    "/stats", dependencies=[Depends(require_roles("admin", "operator", "viewer"))]
)
def get_workbench_stats(db: Session = Depends(get_db)):
    total_runs = db.query(DBTestRun).count()
    runs = db.query(DBTestRun).order_by(desc(DBTestRun.execution_time)).limit(100).all()

    avg_score = 0.0
    if runs:
        avg_score = round(sum(r.total_score for r in runs) / len(runs), 1)

    vendor_counts = {}
    for r in runs:
        vendor_counts[r.source_vendor] = vendor_counts.get(r.source_vendor, 0) + 1

    return {
        "total_test_runs": total_runs,
        "average_interoperability_score": avg_score,
        "active_vendor_adapters": len(list_registered_vendors()),
        "vendor_usage": vendor_counts,
        "recent_runs": [
            {
                "run_id": r.run_id,
                "execution_time": r.execution_time.isoformat() if r.execution_time else None,
                "source_vendor": r.source_vendor,
                "target_vendor": r.target_vendor,
                "total_records": r.total_records,
                "total_score": r.total_score,
                "grade": r.grade
            }
            for r in runs[:10]
        ]
    }


@workbench_router.get(
    "/vendors", dependencies=[Depends(require_roles("admin", "operator", "viewer"))]
)
def get_vendors(db: Session = Depends(get_db)):
    registered = list_registered_vendors()
    # Check if there are database overrides
    customs = db.query(DBCustomVendorConfig).all()
    out = {}
    for vid, prof in registered.items():
        out[vid] = prof.dict()
    for c in customs:
        try:
            cfg = json.loads(c.config_json)
            out[c.vendor_id] = cfg
        except Exception:
            pass
    return out


@workbench_router.post(
    "/generate", dependencies=[Depends(require_roles("admin", "operator", write=True))]
)
def generate_synthetic_data(
    vendor_id: str = Query(..., description="Target vendor format: alpha-hes, beta-hes, gamma-mdms, delta-legacy, or canonical"),
    meter_count: int = Query(3, ge=1, le=20),
    intervals: int = Query(6, ge=1, le=48),
    inject_anomalies: bool = Query(False),
    inject_tampers: bool = Query(False)
):
    if vendor_id == "canonical":
        payload = SyntheticAmiGenerator.generate_canonical_scenario(
            meter_count=meter_count,
            intervals_per_meter=intervals,
            inject_anomalies=inject_anomalies,
            inject_tampers=inject_tampers
        )
        return payload.dict()

    adapter = get_adapter(vendor_id)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported vendor adapter: {vendor_id}")

    data = SyntheticAmiGenerator.generate_vendor_scenario(
        vendor_id=vendor_id,
        meter_count=meter_count,
        intervals=intervals,
        inject_anomalies=inject_anomalies,
        inject_tampers=inject_tampers
    )
    return {
        "vendor_id": vendor_id,
        "format": adapter.profile.format_type,
        "payload": data
    }


def _ensure_payload_size(content_bytes: bytes) -> None:
    """Reject payloads before parsing can consume excessive memory or CPU."""
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.",
        )


async def _read_upload_payload(file: UploadFile) -> str:
    """Read at most the supported text payload size before decoding it."""
    filename = (file.filename or "").lower()
    suffix = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"json", "csv"}:
        raise HTTPException(status_code=415, detail="Only JSON and CSV payload files are supported.")
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in {
        "",
        "application/json",
        "text/json",
        "text/csv",
        "application/csv",
        "text/plain",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=415, detail="Uploaded file content type is not supported.")
    content_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    _ensure_payload_size(content_bytes)
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="Payload file must be UTF-8 encoded.") from error


@workbench_router.post(
    "/workbench/execute",
    dependencies=[Depends(require_roles("admin", "operator", write=True))],
)
async def execute_interoperability_test(
    source_vendor: str = Form(...),
    target_vendor: Optional[str] = Form(None),
    raw_payload: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    content_str = ""
    if file:
        content_str = await _read_upload_payload(file)
    elif raw_payload:
        content_str = raw_payload
    else:
        raise HTTPException(status_code=400, detail="Provide raw_payload or upload a file.")

    return _execute_workbench_payload(source_vendor, target_vendor, content_str, db)


@compare_router.post(
    "/compare", dependencies=[Depends(require_roles("admin", "operator", write=True))]
)
def compare_test_runs(request: CompareRunsInput, db: Session = Depends(get_db)):
    baseline = (
        db.query(DBTestRun).filter(DBTestRun.run_id == request.baseline_run_id).first()
    )
    candidate = (
        db.query(DBTestRun).filter(DBTestRun.run_id == request.candidate_run_id).first()
    )
    if not baseline or not candidate:
        missing_id = (
            request.baseline_run_id if not baseline else request.candidate_run_id
        )
        raise HTTPException(status_code=404, detail=f"Test run {missing_id} not found.")

    baseline_issues = json.loads(baseline.issues_json or "[]")
    candidate_issues = json.loads(candidate.issues_json or "[]")

    def failures(issues: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]:
        grouped: Dict[tuple, List[Dict[str, Any]]] = {}
        for issue in issues:
            if issue.get("severity", "ERROR") not in {"ERROR", "WARNING"}:
                continue
            key = (issue.get("code"), issue.get("field"))
            grouped.setdefault(key, []).append(issue)
        return grouped

    baseline_failures = failures(baseline_issues)
    candidate_failures = failures(candidate_issues)
    resolved = []
    persistent = []
    introduced = []
    for key in baseline_failures.keys() | candidate_failures.keys():
        old_items = baseline_failures.get(key, [])
        new_items = candidate_failures.get(key, [])
        for index in range(max(len(old_items), len(new_items))):
            old_issue = old_items[index] if index < len(old_items) else None
            new_issue = new_items[index] if index < len(new_items) else None
            if old_issue and new_issue:
                persistent.append({"baseline": old_issue, "candidate": new_issue})
            elif old_issue:
                resolved.append(old_issue)
            elif new_issue:
                introduced.append(new_issue)

    score_deltas = {
        "syntactic_score": round(candidate.syntactic_score - baseline.syntactic_score, 1),
        "semantic_score": round(candidate.semantic_score - baseline.semantic_score, 1),
        "data_integrity_score": round(candidate.integrity_score - baseline.integrity_score, 1),
        "total_score": round(candidate.total_score - baseline.total_score, 1),
    }
    return {
        "baseline_run_id": baseline.run_id,
        "candidate_run_id": candidate.run_id,
        "resolved": resolved,
        "persistent": persistent,
        "newly_introduced": introduced,
        "score_deltas": score_deltas,
    }


@roundtrip_router.post(
    "/roundtrip", dependencies=[Depends(require_roles("admin", "operator", write=True))]
)
def roundtrip_payload(request: RoundTripInput):
    try:
        _ensure_payload_size(json.dumps(request.payload, default=str).encode("utf-8"))
    except HTTPException:
        raise
    source_adapter = get_adapter(request.vendor_a)
    target_adapter = get_adapter(request.vendor_b)
    if not source_adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported vendor: {request.vendor_a}")
    if not target_adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported vendor: {request.vendor_b}")
    if source_adapter.profile.format_type == "csv" and not isinstance(request.payload, str):
        raise HTTPException(status_code=422, detail="CSV vendor payload must be a string.")

    source_payload, source_issues = source_adapter.parse_to_canonical(request.payload)
    target_payload = target_adapter.serialize_from_canonical(source_payload)
    if target_adapter.profile.format_type == "csv" and not isinstance(target_payload, str):
        raise HTTPException(status_code=500, detail="CSV adapter returned a non-string payload.")
    roundtrip_payload, target_issues = target_adapter.parse_to_canonical(target_payload)

    differences = []
    before_readings = [
        reading.model_dump(mode="json") for reading in source_payload.readings
    ]
    after_readings = [
        reading.model_dump(mode="json") for reading in roundtrip_payload.readings
    ]
    for index in range(max(len(before_readings), len(after_readings))):
        before = before_readings[index] if index < len(before_readings) else None
        after = after_readings[index] if index < len(after_readings) else None
        if before is None or after is None:
            differences.append(
                {
                    "reading_index": index,
                    "difference": "missing_reading" if before is not None else "extra_reading",
                    "before": before,
                    "after": after,
                }
            )
            continue
        for field in before.keys() | after.keys():
            if before.get(field) != after.get(field):
                differences.append(
                    {
                        "reading_index": index,
                        "meter_serial_number": before.get("meter_serial_number"),
                        "field": field,
                        "before": before.get(field),
                        "after": after.get(field),
                    }
                )

    return {
        "vendor_a": request.vendor_a,
        "vendor_b": request.vendor_b,
        "canonical_payload": source_payload.model_dump(mode="json"),
        "converted_payload": target_payload,
        "roundtrip_canonical_payload": roundtrip_payload.model_dump(mode="json"),
        "field_differences": differences,
        "adapter_issues": [
            issue.model_dump() for issue in source_issues + target_issues
        ],
    }


@suites_router.post(
    "/suites", dependencies=[Depends(require_roles("admin", "operator", write=True))]
)
def create_test_suite(request: SuiteCreateInput, db: Session = Depends(get_db)):
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="Suite name must not be empty.")
    suite = DBTestSuite(
        name=request.name.strip(),
        scenarios_json=json.dumps(request.scenarios, default=str),
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return {
        "id": suite.id,
        "name": suite.name,
        "scenarios": request.scenarios,
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
    }


@suites_router.get(
    "/suites", dependencies=[Depends(require_roles("admin", "operator", "viewer"))]
)
def list_test_suites(db: Session = Depends(get_db)):
    suites = db.query(DBTestSuite).order_by(DBTestSuite.id.desc()).all()
    return [
        {
            "id": suite.id,
            "name": suite.name,
            "scenarios": json.loads(suite.scenarios_json),
            "created_at": suite.created_at.isoformat() if suite.created_at else None,
        }
        for suite in suites
    ]


@suites_router.post(
    "/suites/{suite_id}/run",
    dependencies=[Depends(require_roles("admin", "operator", write=True))],
)
def run_test_suite(suite_id: int, db: Session = Depends(get_db)):
    suite = db.query(DBTestSuite).filter(DBTestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail=f"Test suite {suite_id} not found.")

    scenario_results = []
    passed_count = 0
    for index, scenario in enumerate(json.loads(suite.scenarios_json)):
        source_vendor = scenario.get("source_vendor")
        payload = scenario.get("raw_payload", scenario.get("payload"))
        if not source_vendor or payload is None:
            result = {
                "scenario_index": index,
                "status": "failed",
                "error": "Each scenario requires source_vendor and payload or raw_payload.",
            }
        else:
            content = payload if isinstance(payload, str) else json.dumps(payload)
            try:
                execution = _execute_workbench_payload(
                    source_vendor,
                    scenario.get("target_vendor"),
                    content,
                    db,
                )
                scenario_failed = any(
                    issue.get("severity") == "ERROR"
                    for issue in execution["issues"]
                )
                result = {
                    "scenario_index": index,
                    "status": "failed" if scenario_failed else "passed",
                    "run_id": execution["run_id"],
                    "score": execution["score"],
                    "stages": execution["stages"],
                }
                if not scenario_failed:
                    passed_count += 1
            except HTTPException as error:
                result = {
                    "scenario_index": index,
                    "status": "failed",
                    "error": error.detail,
                }
        scenario_results.append(result)

    suite_run = DBSuiteRun(
        suite_id=suite.id,
        results_json=json.dumps(scenario_results, default=str),
        passed_count=passed_count,
        failed_count=len(scenario_results) - passed_count,
    )
    db.add(suite_run)
    db.commit()
    db.refresh(suite_run)
    return {
        "suite_run_id": suite_run.id,
        "suite_id": suite.id,
        "passed_count": suite_run.passed_count,
        "failed_count": suite_run.failed_count,
        "results": scenario_results,
    }


@workbench_router.get(
    "/test-runs", dependencies=[Depends(require_roles("admin", "operator", "viewer"))]
)
def list_test_runs(limit: int = 50, db: Session = Depends(get_db)):
    runs = db.query(DBTestRun).order_by(desc(DBTestRun.execution_time)).limit(limit).all()
    return [
        {
            "run_id": r.run_id,
            "execution_time": r.execution_time.isoformat() if r.execution_time else None,
            "source_vendor": r.source_vendor,
            "target_vendor": r.target_vendor,
            "total_records": r.total_records,
            "valid_records": r.valid_records,
            "invalid_records": r.invalid_records,
            "total_score": r.total_score,
            "grade": r.grade,
            "summary": r.summary,
            "duration_ms": r.duration_ms,
            "model_version": r.model_version,
            "data_quality_score": r.data_quality_score,
        }
        for r in runs
    ]


@workbench_router.get(
    "/test-runs/{run_id}",
    dependencies=[Depends(require_roles("admin", "operator", "viewer"))],
)
def get_test_run_detail(run_id: str, db: Session = Depends(get_db)):
    r = db.query(DBTestRun).filter(DBTestRun.run_id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail=f"Test run {run_id} not found.")

    issues = []
    try:
        issues = json.loads(r.issues_json or "[]")
    except Exception:
        pass

    return {
        "run_id": r.run_id,
        "execution_time": r.execution_time.isoformat() if r.execution_time else None,
        "source_vendor": r.source_vendor,
        "target_vendor": r.target_vendor,
        "total_records": r.total_records,
        "valid_records": r.valid_records,
        "invalid_records": r.invalid_records,
        "score": {
            "syntactic_score": r.syntactic_score,
            "semantic_score": r.semantic_score,
            "data_integrity_score": r.integrity_score,
            "total_score": r.total_score,
            "grade": r.grade,
            "summary": r.summary
        },
        "issues": issues,
        "raw_preview": r.raw_preview,
        "canonical_preview": r.canonical_preview,
        "target_preview": r.target_preview,
        "duration_ms": r.duration_ms,
        "model_version": r.model_version,
        "data_quality_score": r.data_quality_score,
        "report_url": f"/api/test-runs/{r.run_id}/report.html",
    }


@workbench_router.get(
    "/test-runs/{run_id}/report.html",
    response_class=HTMLResponse,
    dependencies=[Depends(require_roles("admin", "operator", "viewer"))],
)
def export_test_run_report(run_id: str, db: Session = Depends(get_db)):
    """Exportable HTML conformance report built from one stored run."""
    run = db.query(DBTestRun).filter(DBTestRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Test run {run_id} not found.")
    try:
        issues = json.loads(run.issues_json or "[]")
    except json.JSONDecodeError:
        issues = []
    return HTMLResponse(build_run_report(run, issues))


router.include_router(workbench_router)
router.include_router(compare_router)
router.include_router(roundtrip_router)
router.include_router(suites_router)
