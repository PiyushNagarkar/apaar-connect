"""
Anomaly Detection & Risk-Priority Scoring Service (services/anomaly_detection.py).

Implements PART A:
Deterministic Risk-Priority Score per institution-programme-year:
R = w1*S + w2*D + w3*L + w4*C + w5*I

Default weights: 0.30 (S), 0.25 (D), 0.15 (L), 0.10 (C), 0.20 (I) loaded from a
config table (risk_score_configs), where each term is scaled 0-100:
- S: seat-exception severity (share of categories EXCEEDED/NO_APPROVAL, weighted by overage)
- D: duplicate-case severity (open critical/high cases per 100 records)
- L: late-submission rate
- C: correction rate after first submission
- I: identity-failure rate (FAILED only; UNAVAILABLE excluded from numerator and
     reported as "coverage")

Guarantees & Constraints:
- Returns {score, components:[{name, value, weight, contribution}], coverage, reason_codes[], rule_version, label}
- If a component is not measurable, returns null and renormalises remaining weights.
- Never silently treats unknown as zero.
- Mandatory label: "review-priority score, not a probability of misconduct".
- Rule 6: Scores only PRIORITISE human review, never assert guilt or auto-reject.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.correction import CorrectionRequest
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.identity import IdentityCheck
from backend.models.review import ReviewCase
from backend.models.rule_config import RiskScoreConfig
from backend.models.seat import SeatAllocation
from backend.models.submission import Submission
from backend.models.validation import ValidationIssue
from backend.services.seat_compliance import (
    OCCUPIED_STATUSES,
    STATUS_AT_LIMIT,
    STATUS_EXCEEDED,
    STATUS_NEAR_LIMIT,
    STATUS_NO_APPROVAL,
    STATUS_OK,
    calculate_approval_seat_compliance,
)

logger = logging.getLogger(__name__)

# Mandatory regulatory explanation label
REVIEW_PRIORITY_LABEL = "review-priority score, not a probability of misconduct"
DEFAULT_RULE_VERSION = "AICTE_APH_2024_25_V1"

# Default weights from regulatory handbook baseline
DEFAULT_WEIGHTS = {
    "weight_s": 0.30,  # Seat-exception severity
    "weight_d": 0.25,  # Duplicate-case severity
    "weight_l": 0.15,  # Late-submission rate
    "weight_c": 0.10,  # Post-submission correction rate
    "weight_i": 0.20,  # Identity-failure rate
}

# Standardized machine-readable reason codes
REASON_SEAT_EXCEEDED = "SEAT_CAPACITY_EXCEEDED"
REASON_NO_APPROVAL = "NO_STATUTORY_APPROVAL_FOUND"
REASON_CRITICAL_DUPLICATES = "CRITICAL_HIGH_DUPLICATES_PRESENT"
REASON_LATE_SUBMISSIONS = "HIGH_LATE_SUBMISSION_RATE"
REASON_HIGH_CORRECTIONS = "HIGH_POST_SUBMISSION_CORRECTION_RATE"
REASON_IDENTITY_FAILURES = "HIGH_IDENTITY_FAILURE_RATE"
REASON_DEGRADED_COVERAGE = "DEGRADED_IDENTITY_SERVICE_COVERAGE"
REASON_UNMEASURABLE_PREFIX = "COMPONENT_UNMEASURABLE"


# ---------------------------------------------------------------------------
# Weight Resolution from Config Table
# ---------------------------------------------------------------------------

def get_risk_score_weights(
    db: Optional[Session],
    rule_version: Optional[str] = None,
) -> Dict[str, float]:
    """
    Retrieves weights from the risk_score_configs table.
    Falls back to default weights (0.30, 0.25, 0.15, 0.10, 0.20) if not found or inactive.
    """
    weights = dict(DEFAULT_WEIGHTS)
    if db is None:
        return weights

    try:
        query = db.query(RiskScoreConfig).filter(RiskScoreConfig.is_active == True)
        if rule_version:
            cfg = query.filter(RiskScoreConfig.rule_version == rule_version).first()
        else:
            cfg = query.first()

        if cfg:
            if cfg.weight_s is not None:
                weights["weight_s"] = float(cfg.weight_s)
            if cfg.weight_d is not None:
                weights["weight_d"] = float(cfg.weight_d)
            if cfg.weight_l is not None:
                weights["weight_l"] = float(cfg.weight_l)
            if cfg.weight_c is not None:
                weights["weight_c"] = float(cfg.weight_c)
            if cfg.weight_i is not None:
                weights["weight_i"] = float(cfg.weight_i)
    except Exception as e:
        logger.warning("Could not read weights from risk_score_configs, using defaults: %s", e)

    return weights


# ---------------------------------------------------------------------------
# Pure Deterministic Calculator (PART A)
# ---------------------------------------------------------------------------

def calculate_risk_priority_score(
    s_value: Optional[float],
    d_value: Optional[float],
    l_value: Optional[float],
    c_value: Optional[float],
    i_value: Optional[float],
    coverage: Optional[float],
    weights: Optional[Dict[str, float]] = None,
    rule_version: str = DEFAULT_RULE_VERSION,
    reason_codes: Optional[List[str]] = None,
    institution_id: Optional[str] = None,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculates the deterministic Review-Priority Score R:
    R = w1*S + w2*D + w3*L + w4*C + w5*I

    Weight Renormalisation Guarantee:
    If a component is None (not measurable), its weight is distributed
    proportionally among the measurable components.
    Unknown values are NEVER silently treated as zero.
    If all components are None, overall score is None.

    Returns:
    {
      "score": float or None,
      "components": [
        {"name": "seat_exception_severity", "value": ..., "weight": ..., "contribution": ...},
        ...
      ],
      "coverage": float or None,
      "reason_codes": [...],
      "rule_version": "...",
      "label": "review-priority score, not a probability of misconduct"
    }
    """
    w_cfg = dict(DEFAULT_WEIGHTS)
    if weights:
        w_cfg.update(weights)

    # Component definitions: (name, raw_value, config_weight_key)
    raw_components = [
        ("seat_exception_severity", s_value, "weight_s"),
        ("duplicate_case_severity", d_value, "weight_d"),
        ("late_submission_rate", l_value, "weight_l"),
        ("correction_rate", c_value, "weight_c"),
        ("identity_failure_rate", i_value, "weight_i"),
    ]

    reasons: List[str] = list(reason_codes) if reason_codes else []

    # Identify measurable vs unmeasurable components
    measurable = [item for item in raw_components if item[1] is not None]
    unmeasurable = [item for item in raw_components if item[1] is None]

    for name, _, _ in unmeasurable:
        code = f"{REASON_UNMEASURABLE_PREFIX}_{name.upper()}"
        if code not in reasons:
            reasons.append(code)

    components_result: List[Dict[str, Any]] = []

    if not measurable:
        # None of the components could be measured
        for name, _, _ in raw_components:
            components_result.append({
                "name": name,
                "value": None,
                "weight": None,
                "contribution": None,
            })
        return {
            "score": None,
            "components": components_result,
            "coverage": round(coverage, 4) if coverage is not None else None,
            "reason_codes": reasons,
            "rule_version": rule_version,
            "label": REVIEW_PRIORITY_LABEL,
            "institution_id": institution_id,
            "programme": programme,
            "academic_year": academic_year,
        }

    # Sum of original weights for measurable components
    sum_measurable_weights = sum(w_cfg[key] for _, _, key in measurable)

    if sum_measurable_weights <= 0:
        sum_measurable_weights = 1.0

    total_score = 0.0

    # Build component results with renormalised weights
    for name, val, key in raw_components:
        if val is None:
            components_result.append({
                "name": name,
                "value": None,
                "weight": None,
                "contribution": None,
            })
        else:
            # Renormalise weight so sum of measurable weights equals 1.0
            norm_weight = w_cfg[key] / sum_measurable_weights
            val_clamped = min(100.0, max(0.0, float(val)))
            contribution = norm_weight * val_clamped
            total_score += contribution

            components_result.append({
                "name": name,
                "value": round(val_clamped, 2),
                "weight": round(norm_weight, 4),
                "contribution": round(contribution, 2),
            })

    final_score = min(100.0, max(0.0, round(total_score, 2)))

    # Automatically attach indicator reason codes if not already present
    if s_value is not None and s_value > 0 and REASON_SEAT_EXCEEDED not in reasons:
        reasons.append(REASON_SEAT_EXCEEDED)
    if d_value is not None and d_value > 0 and REASON_CRITICAL_DUPLICATES not in reasons:
        reasons.append(REASON_CRITICAL_DUPLICATES)
    if l_value is not None and l_value > 5.0 and REASON_LATE_SUBMISSIONS not in reasons:
        reasons.append(REASON_LATE_SUBMISSIONS)
    if c_value is not None and c_value > 5.0 and REASON_HIGH_CORRECTIONS not in reasons:
        reasons.append(REASON_HIGH_CORRECTIONS)
    if i_value is not None and i_value > 5.0 and REASON_IDENTITY_FAILURES not in reasons:
        reasons.append(REASON_IDENTITY_FAILURES)
    if coverage is not None and coverage < 0.90 and REASON_DEGRADED_COVERAGE not in reasons:
        reasons.append(REASON_DEGRADED_COVERAGE)

    return {
        "score": final_score,
        "components": components_result,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "reason_codes": reasons,
        "rule_version": rule_version,
        "label": REVIEW_PRIORITY_LABEL,
        "institution_id": institution_id,
        "programme": programme,
        "academic_year": academic_year,
    }


# ---------------------------------------------------------------------------
# Database-Backed Component Extractors
# ---------------------------------------------------------------------------

def compute_seat_exception_severity(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """
    Computes S: Seat-exception severity (0-100).
    S = share of categories EXCEEDED/NO_APPROVAL, weighted by overage.

    For each category:
    - Status OK / NEAR_LIMIT / AT_LIMIT: severity = 0
    - Status NO_APPROVAL: severity weight = 1.5
    - Status EXCEEDED: overage_ratio = (occupied - approved) / approved
      severity weight = 1.0 + min(2.0, overage_ratio)
    S = min(100.0, (sum(category_weights) / total_categories) * 100)
    """
    reason_codes: List[str] = []

    # Find matching approvals
    q = db.query(ProgramApproval).filter(ProgramApproval.institution_id == institution_id)
    if programme:
        q = q.filter(ProgramApproval.programme == programme)
    if academic_year:
        q = q.filter(ProgramApproval.academic_year == academic_year)

    approvals = q.all()

    # If no approvals found
    if not approvals:
        # Check if admissions exist without approval
        eq = db.query(Enrollment).filter(Enrollment.institution_id == institution_id)
        if academic_year:
            eq = eq.filter(Enrollment.academic_year == academic_year)
        if eq.count() > 0:
            reason_codes.append(REASON_NO_APPROVAL)
            return 100.0, reason_codes
        # Neither approval nor enrollments exist -> unmeasurable
        return None, reason_codes

    total_categories = 0
    total_violation_weight = 0.0

    for app in approvals:
        compliance = calculate_approval_seat_compliance(db, app.id)
        by_seat = compliance.get("by_seat_type", {})
        if not by_seat:
            continue

        for st_name, metrics in by_seat.items():
            total_categories += 1
            st_status = metrics.get("status")
            approved = metrics.get("approved", 0)
            occupied = metrics.get("occupied", 0)

            if st_status == STATUS_EXCEEDED:
                overage = max(0, occupied - approved)
                overage_ratio = overage / max(1, approved)
                weight = 1.0 + min(2.0, overage_ratio)
                total_violation_weight += weight
                if REASON_SEAT_EXCEEDED not in reason_codes:
                    reason_codes.append(REASON_SEAT_EXCEEDED)
            elif st_status == STATUS_NO_APPROVAL:
                total_violation_weight += 1.5
                if REASON_NO_APPROVAL not in reason_codes:
                    reason_codes.append(REASON_NO_APPROVAL)

    if total_categories == 0:
        return None, reason_codes

    severity = (total_violation_weight / total_categories) * 100.0
    return min(100.0, max(0.0, round(severity, 2))), reason_codes


def compute_duplicate_severity(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Tuple[Optional[float], int]:
    """
    Computes D: Duplicate-case severity (0-100).
    D = open critical/high cases per 100 records.
    D = min(100.0, (open_critical_high_dups / total_records) * 100).
    If total_records == 0: returns (None, 0).
    """
    # Count total student records
    eq = db.query(Enrollment).filter(Enrollment.institution_id == institution_id)
    if academic_year:
        eq = eq.filter(Enrollment.academic_year == academic_year)
    if programme:
        eq = eq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
            ProgramApproval.programme == programme
        )

    total_records = eq.count()
    if total_records == 0:
        return None, 0

    # Count open critical/high duplicate review cases
    rq = (
        db.query(ReviewCase)
        .filter(ReviewCase.institution_id == institution_id)
        .filter(ReviewCase.status.in_(["OPEN", "ASSIGNED", "AWAITING_INSTITUTION", "UNDER_DECISION"]))
        .filter(ReviewCase.severity.in_(["CRITICAL", "HIGH"]))
        .filter(ReviewCase.type.in_(["DUPLICATE", "DUPLICATE_MATCH", "DUPLICATE_APAAR", "DUPLICATE_APAAR_MATCH"]))
    )

    if programme or academic_year:
        rq = rq.join(Enrollment, ReviewCase.enrollment_id == Enrollment.id)
        if academic_year:
            rq = rq.filter(Enrollment.academic_year == academic_year)
        if programme:
            rq = rq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
                ProgramApproval.programme == programme
            )

    open_crit_high_dups = rq.count()
    rate_per_hundred = (open_crit_high_dups / total_records) * 100.0
    d_score = min(100.0, max(0.0, round(rate_per_hundred, 2)))

    return d_score, total_records


def compute_late_submission_rate(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Tuple[Optional[float], int]:
    """
    Computes L: Late-submission rate (0-100).
    Checks enrollments/submissions submitted post-deadline, under locked round,
    or flagged with RULE_L3_LATE_SUBMISSION.
    """
    eq = db.query(Enrollment).filter(Enrollment.institution_id == institution_id)
    if academic_year:
        eq = eq.filter(Enrollment.academic_year == academic_year)
    if programme:
        eq = eq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
            ProgramApproval.programme == programme
        )

    total_records = eq.count()
    if total_records == 0:
        # Check submissions if enrollments not yet committed
        sq = db.query(Submission).filter(Submission.institution_id == institution_id)
        if academic_year:
            sq = sq.filter(Submission.academic_year == academic_year)
        if programme:
            sq = sq.filter(Submission.programme == programme)
        tot_sub = sq.count()
        if tot_sub == 0:
            return None, 0
        late_sub = sq.filter(Submission.is_locked == True).count()
        return min(100.0, round((late_sub / tot_sub) * 100.0, 2)), tot_sub

    # Count enrollments with late submission validation issues or locked submission
    late_enrollments = (
        db.query(Enrollment.id)
        .filter(Enrollment.institution_id == institution_id)
        .join(ValidationIssue, ValidationIssue.enrollment_id == Enrollment.id)
        .filter(ValidationIssue.rule_code.in_(["RULE_L3_LATE_SUBMISSION", "RULE_L2_LATE_SUBMISSION_WITHOUT_REASON"]))
    )
    if academic_year:
        late_enrollments = late_enrollments.filter(Enrollment.academic_year == academic_year)
    if programme:
        late_enrollments = late_enrollments.join(
            ProgramApproval, Enrollment.approval_id == ProgramApproval.id
        ).filter(ProgramApproval.programme == programme)

    late_count = late_enrollments.distinct().count()
    late_rate = (late_count / total_records) * 100.0
    return min(100.0, max(0.0, round(late_rate, 2))), total_records


def compute_correction_rate(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Tuple[Optional[float], int]:
    """
    Computes C: Correction rate after first submission (0-100).
    Counts records that had correction requests or version > 1 after initial admission.
    """
    eq = db.query(Enrollment).filter(Enrollment.institution_id == institution_id)
    if academic_year:
        eq = eq.filter(Enrollment.academic_year == academic_year)
    if programme:
        eq = eq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
            ProgramApproval.programme == programme
        )

    total_records = eq.count()
    if total_records == 0:
        return None, 0

    # Records with version > 1 or with a CorrectionRequest
    corrected_q = (
        db.query(Enrollment.id)
        .outerjoin(CorrectionRequest, CorrectionRequest.enrollment_id == Enrollment.id)
        .filter(Enrollment.institution_id == institution_id)
        .filter((Enrollment.version > 1) | (CorrectionRequest.id != None))
    )
    if academic_year:
        corrected_q = corrected_q.filter(Enrollment.academic_year == academic_year)
    if programme:
        corrected_q = corrected_q.join(
            ProgramApproval, Enrollment.approval_id == ProgramApproval.id
        ).filter(ProgramApproval.programme == programme)

    corrected_count = corrected_q.distinct().count()
    corr_rate = (corrected_count / total_records) * 100.0
    return min(100.0, max(0.0, round(corr_rate, 2))), total_records


def compute_identity_failure_rate(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float], int]:
    """
    Computes I: Identity-failure rate (0-100) and Coverage (0-1).
    Requirement:
    - FAILED only in numerator!
    - UNAVAILABLE excluded from numerator and reported as 'coverage'.
    - If total records == 0: returns (None, None, 0).
    - If passed + failed == 0: failure rate is unmeasurable (None), coverage is reported.
    """
    eq = db.query(Enrollment).filter(Enrollment.institution_id == institution_id)
    if academic_year:
        eq = eq.filter(Enrollment.academic_year == academic_year)
    if programme:
        eq = eq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
            ProgramApproval.programme == programme
        )

    records = eq.all()
    total_records = len(records)
    if total_records == 0:
        return None, None, 0

    passed_count = sum(1 for r in records if (r.identity_status or "").upper() in ("PASS", "PASSED"))
    failed_count = sum(1 for r in records if (r.identity_status or "").upper() in ("FAIL", "FAILED"))

    available_checks = passed_count + failed_count
    coverage = available_checks / total_records

    if available_checks == 0:
        # Zero completed identity checks -> failure rate is not measurable
        return None, round(coverage, 4), total_records

    # FAILED only; UNAVAILABLE is excluded from numerator
    failure_rate = (failed_count / available_checks) * 100.0
    i_score = min(100.0, max(0.0, round(failure_rate, 2)))

    return i_score, round(coverage, 4), total_records


# ---------------------------------------------------------------------------
# Database-Backed End-to-End Runner (PART A)
# ---------------------------------------------------------------------------

def compute_risk_priority_score(
    db: Session,
    institution_id: str,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
    rule_version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes the complete, deterministic Review-Priority Score for an
    institution-programme-year directly from the database.
    """
    active_rule_version = rule_version or DEFAULT_RULE_VERSION

    # 1. Load weights from config table
    weights = get_risk_score_weights(db, active_rule_version)

    reason_codes: List[str] = []

    # 2. Extract S (Seat-exception severity)
    s_val, s_reasons = compute_seat_exception_severity(
        db, institution_id, programme=programme, academic_year=academic_year
    )
    reason_codes.extend(s_reasons)

    # 3. Extract D (Duplicate-case severity)
    d_val, _ = compute_duplicate_severity(
        db, institution_id, programme=programme, academic_year=academic_year
    )

    # 4. Extract L (Late-submission rate)
    l_val, _ = compute_late_submission_rate(
        db, institution_id, programme=programme, academic_year=academic_year
    )

    # 5. Extract C (Correction rate)
    c_val, _ = compute_correction_rate(
        db, institution_id, programme=programme, academic_year=academic_year
    )

    # 6. Extract I (Identity-failure rate and coverage)
    i_val, coverage, _ = compute_identity_failure_rate(
        db, institution_id, programme=programme, academic_year=academic_year
    )

    # 7. Synthesise deterministic score with renormalisation
    result = calculate_risk_priority_score(
        s_value=s_val,
        d_value=d_val,
        l_value=l_val,
        c_value=c_val,
        i_value=i_val,
        coverage=coverage,
        weights=weights,
        rule_version=active_rule_version,
        reason_codes=reason_codes,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
    )

    return result


# ---------------------------------------------------------------------------
# Anomaly Detection Scanners
# ---------------------------------------------------------------------------

def detect_seat_capacity_anomalies(
    db: Session,
    institution_id: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Scans for seat capacity anomalies across all approvals:
    - EXCEEDED allocations (overflow beyond statutory ceiling)
    - NO_APPROVAL unapproved student enrollments
    - NEAR_LIMIT (>= 95% utilization warning)
    """
    anomalies: List[Dict[str, Any]] = []

    q = db.query(ProgramApproval)
    if institution_id:
        q = q.filter(ProgramApproval.institution_id == institution_id)
    if academic_year:
        q = q.filter(ProgramApproval.academic_year == academic_year)

    approvals = q.all()

    for app in approvals:
        compliance = calculate_approval_seat_compliance(db, app.id)
        by_seat = compliance.get("by_seat_type", {})
        for st_name, m in by_seat.items():
            status = m.get("status")
            if status in (STATUS_EXCEEDED, STATUS_NO_APPROVAL, STATUS_NEAR_LIMIT):
                anomalies.append({
                    "type": "SEAT_CAPACITY_ANOMALY",
                    "severity": "CRITICAL" if status == STATUS_EXCEEDED else ("HIGH" if status == STATUS_NO_APPROVAL else "MEDIUM"),
                    "institution_id": app.institution_id,
                    "programme": app.programme,
                    "branch": app.branch,
                    "academic_year": app.academic_year,
                    "seat_type": st_name,
                    "approved": m.get("approved"),
                    "occupied": m.get("occupied"),
                    "status": status,
                    "utilisation_pct": m.get("utilisation_pct"),
                    "message": f"Seat category '{st_name}' status is {status} with {m.get('occupied')}/{m.get('approved')} seats occupied.",
                })

    return anomalies


def detect_duplicate_spikes(
    db: Session,
    threshold_rate: float = 3.0,
) -> List[Dict[str, Any]]:
    """
    Detects programs or institutions with duplicate case rates exceeding threshold_rate per 100 records.
    """
    spikes: List[Dict[str, Any]] = []

    # Query distinct institution and academic years
    combos = (
        db.query(Enrollment.institution_id, Enrollment.academic_year)
        .distinct()
        .all()
    )

    for inst_id, ay in combos:
        d_val, total = compute_duplicate_severity(db, inst_id, academic_year=ay)
        if d_val is not None and d_val >= threshold_rate:
            spikes.append({
                "type": "DUPLICATE_SPIKE_ANOMALY",
                "severity": "CRITICAL" if d_val >= 10.0 else "HIGH",
                "institution_id": inst_id,
                "academic_year": ay,
                "total_records": total,
                "duplicate_rate_per_hundred": d_val,
                "threshold": threshold_rate,
                "message": f"High concentration of open critical/high duplicates: {d_val} cases per 100 records.",
            })

    return spikes


def scan_institution_anomalies(
    db: Session,
    institution_id: str,
    academic_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Comprehensive anomaly audit report for a given institution:
    - Risk-Priority Score
    - Seat Capacity Anomalies
    - Duplicate Flags
    - Coverage Status
    """
    risk_summary = compute_risk_priority_score(db, institution_id, academic_year=academic_year)
    seat_anomalies = detect_seat_capacity_anomalies(db, institution_id, academic_year=academic_year)

    return {
        "institution_id": institution_id,
        "academic_year": academic_year,
        "risk_priority": risk_summary,
        "seat_anomalies": seat_anomalies,
        "anomaly_count": len(seat_anomalies),
        "review_priority_label": REVIEW_PRIORITY_LABEL,
    }
