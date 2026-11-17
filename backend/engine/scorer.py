"""Compatibility Scoring and Diagnostic Suggestion Engine for VidyutSetu."""

from typing import List, Dict, Any
from backend.models.canonical import (
    DiagnosticIssue,
    IssueSeverity,
    CompatibilityScoreBreakdown
)


class ScoringEngine:
    """Calculates transparent 3-pillar interoperability score and diagnostic recommendations."""

    @classmethod
    def calculate_score(
        cls,
        total_records: int,
        issues: List[DiagnosticIssue],
        format_parsed_successfully: bool = True
    ) -> CompatibilityScoreBreakdown:
        if total_records == 0:
            return CompatibilityScoreBreakdown(
                syntactic_score=0.0,
                semantic_score=0.0,
                data_integrity_score=0.0,
                total_score=0.0,
                grade="INCOMPLETE",
                summary=(
                    "Incomplete assessment: no canonical meter readings were available "
                    "for interoperability scoring."
                ),
            )

        error_count = sum(1 for i in issues if i.severity == IssueSeverity.ERROR)
        warning_count = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)

        # 1. Syntactic Score (Weight: 30%)
        # Deduct heavily for parsing failures, missing schema envelopes, or corrupt syntax
        if not format_parsed_successfully:
            syntactic_score = 0.0
        else:
            syntax_errors = sum(1 for i in issues if i.code in (
                "JSON_PARSE_ERROR", "CSV_PARSE_FAILED", "INVALID_PAYLOAD_STRUCTURE",
                "MISSING_CSV_COLUMNS", "INVALID_TELEMETRY_STRUCTURE"
            ))
            syntactic_deduction = min(100.0, syntax_errors * 25.0)
            syntactic_score = max(0.0, 100.0 - syntactic_deduction)

        # 2. Semantic Score (Weight: 40%)
        # Deduct for missing mandatory canonical fields, unmapped OBIS codes, bad types, timezone omission
        semantic_errors = sum(1 for i in issues if i.code in (
            "MISSING_ACTIVE_IMPORT_ENERGY", "MISSING_METER_ID", "EMPTY_METER_ID",
            "MISSING_DEVICE_UID", "MISSING_ACT_WH", "INVALID_TIMESTAMP_FORMAT",
            "NUMBER_COERCION_ERROR", "POWER_FACTOR_OUT_OF_RANGE", "NAIVE_TIMESTAMP"
        ))
        semantic_deduction = min(100.0, (semantic_errors / total_records) * 60.0 + (warning_count * 2.0))
        semantic_score = max(0.0, 100.0 - semantic_deduction)

        # 3. Data Integrity & Physical Conformance Score (Weight: 30%)
        # Deduct for non-monotonic energy, electrical limits exceeded, negative energy/current, future timestamps
        integrity_errors = sum(1 for i in issues if i.code in (
            "NON_MONOTONIC_ENERGY_REGISTER", "NEGATIVE_ACTIVE_ENERGY", "NEGATIVE_CURRENT",
            "FUTURE_TIMESTAMP", "VOLTAGE_OUT_OF_BOUNDS", "OVERCURRENT_ALARM",
            "GRID_FREQUENCY_ABNORMAL", "DUPLICATE_INTERVAL_TIMESTAMP"
        ))
        integrity_deduction = min(100.0, (integrity_errors / total_records) * 80.0)
        data_integrity_score = max(0.0, 100.0 - integrity_deduction)

        # Composite Weighted Total
        total_score = round(
            (syntactic_score * 0.30) +
            (semantic_score * 0.40) +
            (data_integrity_score * 0.30),
            1
        )

        # Grade calculation
        if total_score >= 95.0:
            grade = "A+"
            summary = "Fully Interoperable: Meets all IEC 61968-9 and DLMS/COSEM canonical criteria without translation impedance."
        elif total_score >= 85.0:
            grade = "A"
            summary = "Production Ready: Minor non-critical discrepancies (e.g. naive timezones or mild clock offsets) that auto-remediate."
        elif total_score >= 70.0:
            grade = "B"
            summary = "Conditionally Compatible: Requires field mapping adjustments or unit multipliers before enterprise MDMS ingestion."
        elif total_score >= 50.0:
            grade = "C"
            summary = "Degraded Interoperability: Contains severe schema omissions, out-of-range electrical values, or non-monotonic registers."
        else:
            grade = "F"
            summary = "Non-Interoperable: Major structural or syntactic failures; cannot be safely mapped to canonical data model."

        return CompatibilityScoreBreakdown(
            syntactic_score=round(syntactic_score, 1),
            semantic_score=round(semantic_score, 1),
            data_integrity_score=round(data_integrity_score, 1),
            total_score=total_score,
            grade=grade,
            summary=summary
        )

    @classmethod
    def calculate_data_quality(
        cls,
        total_records: int,
        valid_records: int,
        issues: List[DiagnosticIssue],
    ) -> Dict[str, Any]:
        """Record-level data quality for one run (rule-derived, transparent).

        Unlike the interoperability score, this measures how much of the submitted
        data survived canonicalization and how densely issues are attached to the
        records that were processed. Nothing here is learned or hardcoded per run.
        """
        records = max(total_records, 1)
        error_count = sum(1 for issue in issues if issue.severity == IssueSeverity.ERROR)
        warning_count = sum(
            1 for issue in issues if issue.severity == IssueSeverity.WARNING
        )
        record_validity_pct = round(min(100.0, (valid_records / records) * 100.0), 1)
        issue_density_pct = round(
            min(100.0, ((error_count + (0.5 * warning_count)) / records) * 100.0), 1
        )
        score = round(max(0.0, min(100.0, record_validity_pct - (issue_density_pct * 0.25))), 1)
        return {
            "score": score,
            "record_validity_pct": record_validity_pct,
            "issue_density_pct": issue_density_pct,
            "error_count": error_count,
            "warning_count": warning_count,
            "source": "rule",
        }


class DiagnosticSuggester:
    """Provides actionable remediation rules and configurations based on detected issues."""

    @classmethod
    def enrich_issues_with_remediation(cls, issues: List[DiagnosticIssue]) -> List[DiagnosticIssue]:
        for issue in issues:
            if not issue.suggested_fix:
                if issue.code == "POWER_FACTOR_OUT_OF_RANGE":
                    issue.suggested_fix = "Configure rule: `power_factor = raw_value * 0.01` if vendor reports percentage (0-100%)."
                elif issue.code == "MISSING_ACTIVE_IMPORT_ENERGY":
                    issue.suggested_fix = "Map vendor import register (e.g. OBIS `1.0.1.8.0.255` or column `KWH_IMP`) in adapter config."
                elif issue.code == "NON_MONOTONIC_ENERGY_REGISTER":
                    issue.suggested_fix = "Apply rollover threshold filter (> 99999 kWh) or flag meter for physical calibration inspection."
                elif issue.code == "VOLTAGE_OUT_OF_BOUNDS":
                    issue.suggested_fix = "Verify whether values are line-to-line (400V) or apply PT scaling factor (e.g. 0.001 for mV)."
                elif issue.code == "NAIVE_TIMESTAMP":
                    issue.suggested_fix = "Set default timezone to `Asia/Kolkata` (+05:30) or append UTC designator 'Z'."
        return issues
