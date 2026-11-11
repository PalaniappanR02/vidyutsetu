"""REST API Routes for VidyutSetu Workbench."""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.db.database import get_db, DBTestRun, DBCustomVendorConfig
from backend.adapters.registry import get_adapter, list_registered_vendors
from backend.engine.validator import ValidationEngine
from backend.engine.scorer import ScoringEngine, DiagnosticSuggester
from backend.generator.simulator import SyntheticAmiGenerator
from backend.models.canonical import (
    CanonicalPayload,
    DiagnosticIssue,
    TestExecutionReport,
    CompatibilityScoreBreakdown
)
from backend.models.vendor import VendorProfile

router = APIRouter(prefix="/api", tags=["Workbench API"])


@router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "VidyutSetu AMI Interoperability Workbench",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }


@router.get("/stats")
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


@router.get("/vendors")
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


@router.post("/generate")
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


@router.post("/workbench/execute")
async def execute_interoperability_test(
    source_vendor: str = Form(...),
    target_vendor: Optional[str] = Form(None),
    raw_payload: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    start_time = time.time()
    source_adapter = get_adapter(source_vendor)
    if not source_adapter:
        raise HTTPException(status_code=400, detail=f"Source vendor '{source_vendor}' is not recognized.")

    # Determine input string
    content_str = ""
    if file:
        content_bytes = await file.read()
        content_str = content_bytes.decode("utf-8", errors="replace")
    elif raw_payload:
        content_str = raw_payload
    else:
        raise HTTPException(status_code=400, detail="Provide raw_payload or upload a file.")

    # Ingest and parse to canonical
    parsing_succeeded = True
    parsed_input = content_str
    if source_adapter.profile.format_type == "json":
        try:
            parsed_input = json.loads(content_str)
        except Exception:
            parsing_succeeded = False

    canonical_payload, adapter_issues = source_adapter.parse_to_canonical(parsed_input)

    # Validate canonical payload
    validation_issues, valid_count, invalid_count = ValidationEngine.validate_canonical_payload(canonical_payload)
    all_issues = adapter_issues + validation_issues

    # Enrich issues with auto-remediation advice
    all_issues = DiagnosticSuggester.enrich_issues_with_remediation(all_issues)

    # Calculate transparent score
    total_records = len(canonical_payload.readings)
    score_breakdown = ScoringEngine.calculate_score(
        total_records=total_records,
        issues=all_issues,
        format_parsed_successfully=parsing_succeeded
    )

    # If target vendor requested, serialize to target format
    target_output = None
    if target_vendor and target_vendor != "none":
        target_adapter = get_adapter(target_vendor)
        if target_adapter:
            target_output = target_adapter.serialize_from_canonical(canonical_payload)

    elapsed_ms = round((time.time() - start_time) * 1000.0, 2)
    run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"

    # Persist in SQLite
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
        issues_json=json.dumps([iss.dict() for iss in all_issues]),
        raw_preview=content_str[:5000],
        canonical_preview=json.dumps(canonical_payload.dict(), default=str)[:10000],
        target_preview=json.dumps(target_output, default=str)[:10000] if isinstance(target_output, (dict, list)) else (str(target_output)[:10000] if target_output else ""),
        duration_ms=elapsed_ms
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
        "score": score_breakdown.dict(),
        "issues": [iss.dict() for iss in all_issues],
        "canonical_payload": canonical_payload.dict(),
        "target_output": target_output,
        "duration_ms": elapsed_ms
    }


@router.get("/test-runs")
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
            "duration_ms": r.duration_ms
        }
        for r in runs
    ]


@router.get("/test-runs/{run_id}")
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
        "duration_ms": r.duration_ms
    }
