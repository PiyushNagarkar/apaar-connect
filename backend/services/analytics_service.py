"""
Analytics & Data-Quality Scoring Service (services/analytics_service.py).

Implements:
1. PART B: Data-Quality Score Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))
   where:
   - M: missing-required-field rate (0-1 rate, states denominator)
   - V: unresolved validation errors rate (0-1 rate, states denominator)
   - D: unresolved duplicate cases rate (0-1 rate, states denominator)
   - A: approval mismatches rate (0-1 rate, states denominator)
   - T: late submissions rate (0-1 rate, states denominator)
   Returns component rates alongside Q.

2. National and Institution-level dashboard analytics (Rule 11):
   - Dynamic DB computation (no hardcoded demo numbers)
   - Verification funnel counts (L1, L2, L3 pass/fail/unavailable)
   - Category-isolated seat utilization metrics (Rule 3)
   - Open review queue summaries
   - Integration with Risk-Priority Score (PART A)
"""
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation
from backend.models.student import Student
from backend.models.submission import Submission, SubmissionRow
from backend.models.validation import ValidationIssue
from backend.schemas.analytics import (
    CategorySeatMetric,
    DataQualityComponent,
    DataQualityScoreResponse,
    InstitutionDashboardAnalytics,
    ProgramSeatMetric,
    ReviewQueueSummary,
    SystemOverviewAnalytics,
    VerificationFunnelMetric,
)
from backend.services.anomaly_detection import compute_risk_priority_score
from backend.services.seat_compliance import (
    OCCUPIED_STATUSES,
    STATUS_EXCEEDED,
    calculate_approval_seat_compliance,
)

logger = logging.getLogger(__name__)

# Required core fields for student admission compliance evaluation
REQUIRED_STUDENT_FIELDS = [
    "name",
    "dob",
    "gender",
    "category",
    "seat_type",
    "admission_date",
    "apaar_masked",
]

# Weights for Q point deductions (sum to 100)
WEIGHT_M = 35.0  # Missing required fields
WEIGHT_V = 25.0  # Unresolved validation errors
WEIGHT_D = 20.0  # Unresolved duplicate cases
WEIGHT_A = 10.0  # Approval mismatches
WEIGHT_T = 10.0  # Late submissions


# ---------------------------------------------------------------------------
# Pure Deterministic Calculator (PART B)
# ---------------------------------------------------------------------------

def calculate_data_quality_score(
    m_rate: float,
    v_rate: float,
    d_rate: float,
    a_rate: float,
    t_rate: float,
    m_numerator: int = 0,
    m_denominator: int = 0,
    v_numerator: int = 0,
    v_denominator: int = 0,
    d_numerator: int = 0,
    d_denominator: int = 0,
    a_numerator: int = 0,
    a_denominator: int = 0,
    t_numerator: int = 0,
    t_denominator: int = 0,
    total_records: int = 0,
    institution_id: Optional[str] = None,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T)).
    All rates M, V, D, A, T must be between 0.0 and 1.0.
    Returns component rates alongside Q, explicitly stating each denominator.
    """
    # Clamp rates strictly to [0.0, 1.0]
    m = min(1.0, max(0.0, float(m_rate)))
    v = min(1.0, max(0.0, float(v_rate)))
    d = min(1.0, max(0.0, float(d_rate)))
    a = min(1.0, max(0.0, float(a_rate)))
    t = min(1.0, max(0.0, float(t_rate)))

    deduction = (
        (WEIGHT_M * m)
        + (WEIGHT_V * v)
        + (WEIGHT_D * d)
        + (WEIGHT_A * a)
        + (WEIGHT_T * t)
    )

    q_score = max(0.0, round(100.0 - deduction, 2))

    # Determine grade tier
    if q_score >= 90.0:
        grade = "EXCELLENT"
    elif q_score >= 75.0:
        grade = "GOOD"
    elif q_score >= 50.0:
        grade = "FAIR"
    else:
        grade = "POOR"

    components = {
        "missing_required_fields": {
            "symbol": "M",
            "name": "Missing Required Field Rate",
            "rate": round(m, 4),
            "numerator": m_numerator,
            "denominator": m_denominator,
            "denominator_description": f"Total required fields evaluated ({m_denominator}) across {total_records} student records",
            "weight": WEIGHT_M,
            "penalty": round(WEIGHT_M * m, 2),
        },
        "unresolved_validation_errors": {
            "symbol": "V",
            "name": "Unresolved Validation Errors Rate",
            "rate": round(v, 4),
            "numerator": v_numerator,
            "denominator": v_denominator,
            "denominator_description": f"Total student records evaluated ({v_denominator})",
            "weight": WEIGHT_V,
            "penalty": round(WEIGHT_V * v, 2),
        },
        "unresolved_duplicate_cases": {
            "symbol": "D",
            "name": "Unresolved Duplicate Cases Rate",
            "rate": round(d, 4),
            "numerator": d_numerator,
            "denominator": d_denominator,
            "denominator_description": f"Total student records evaluated ({d_denominator})",
            "weight": WEIGHT_D,
            "penalty": round(WEIGHT_D * d, 2),
        },
        "approval_mismatches": {
            "symbol": "A",
            "name": "Approval Mismatches Rate",
            "rate": round(a, 4),
            "numerator": a_numerator,
            "denominator": a_denominator,
            "denominator_description": f"Total student records evaluated ({a_denominator})",
            "weight": WEIGHT_A,
            "penalty": round(WEIGHT_A * a, 2),
        },
        "late_submissions": {
            "symbol": "T",
            "name": "Late Submissions Rate",
            "rate": round(t, 4),
            "numerator": t_numerator,
            "denominator": t_denominator,
            "denominator_description": f"Total student records evaluated ({t_denominator})",
            "weight": WEIGHT_T,
            "penalty": round(WEIGHT_T * t, 2),
        },
    }

    return {
        "score": q_score,
        "grade": grade,
        "formula": "Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))",
        "components": components,
        "total_records_evaluated": total_records,
        "institution_id": institution_id,
        "programme": programme,
        "academic_year": academic_year,
    }


# ---------------------------------------------------------------------------
# Database-Backed Component Extractors (PART B)
# ---------------------------------------------------------------------------

def compute_data_quality_score(
    db: Session,
    institution_id: Optional[str] = None,
    programme: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts M, V, D, A, T directly from database tables, calculates Q score,
    and returns component defect rates alongside Q, stating each denominator.
    """
    # 1. Fetch matching student enrollment records
    eq = db.query(Enrollment)
    if institution_id:
        eq = eq.filter(Enrollment.institution_id == institution_id)
    if academic_year:
        eq = eq.filter(Enrollment.academic_year == academic_year)
    if programme:
        eq = eq.join(ProgramApproval, Enrollment.approval_id == ProgramApproval.id).filter(
            ProgramApproval.programme == programme
        )

    enrollments = eq.all()
    total_records = len(enrollments)

    if total_records == 0:
        # If no records exist, return default clean score 100 with zero denominators
        return calculate_data_quality_score(
            m_rate=0.0,
            v_rate=0.0,
            d_rate=0.0,
            a_rate=0.0,
            t_rate=0.0,
            m_numerator=0,
            m_denominator=0,
            v_numerator=0,
            v_denominator=0,
            d_numerator=0,
            d_denominator=0,
            a_numerator=0,
            a_denominator=0,
            t_numerator=0,
            t_denominator=0,
            total_records=0,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
        )

    enrollment_ids = [e.id for e in enrollments]
    student_ids = [e.student_id for e in enrollments]

    # -----------------------------------------------------------------------
    # M: Missing-required-field rate
    # Check students & enrollments for empty or null core fields
    # -------------------------------------------------------
    students_by_id = {
        s.id: s
        for s in db.query(Student).filter(Student.id.in_(student_ids)).all()
    }

    missing_field_count = 0
    total_required_fields_checked = total_records * len(REQUIRED_STUDENT_FIELDS)

    for e in enrollments:
        s = students_by_id.get(e.student_id)
        # Check student fields
        if not s or not s.name or not str(s.name).strip():
            missing_field_count += 1
        if not s or s.dob is None:
            missing_field_count += 1
        if not s or not s.gender or not str(s.gender).strip():
            missing_field_count += 1
        if not s or not s.apaar_masked or not str(s.apaar_masked).strip():
            missing_field_count += 1

        # Check enrollment fields
        if not e.category or not str(e.category).strip():
            missing_field_count += 1
        if not e.seat_type or not str(e.seat_type).strip():
            missing_field_count += 1
        if e.admission_date is None:
            missing_field_count += 1

    m_rate = (
        missing_field_count / total_required_fields_checked
        if total_required_fields_checked > 0
        else 0.0
    )

    # -----------------------------------------------------------------------
    # V: Unresolved validation errors rate
    # Count records having open ERROR, CRITICAL, or REGULATORY_ALERT issues
    # -----------------------------------------------------------------------
    v_issues = (
        db.query(ValidationIssue.enrollment_id)
        .filter(ValidationIssue.enrollment_id.in_(enrollment_ids))
        .filter(ValidationIssue.status == "OPEN")
        .filter(ValidationIssue.severity.in_(["ERROR", "CRITICAL", "REGULATORY_ALERT", "HIGH"]))
        .distinct()
        .all()
    )
    v_numerator = len(v_issues)
    v_rate = min(1.0, v_numerator / total_records)

    # -----------------------------------------------------------------------
    # D: Unresolved duplicate cases rate
    # Count open duplicate review cases or candidate pairs
    # -----------------------------------------------------------------------
    d_cases = (
        db.query(ReviewCase.enrollment_id)
        .filter(ReviewCase.enrollment_id.in_(enrollment_ids))
        .filter(ReviewCase.status.in_(["OPEN", "ASSIGNED", "AWAITING_INSTITUTION", "UNDER_DECISION"]))
        .filter(ReviewCase.type.in_(["DUPLICATE", "DUPLICATE_MATCH", "DUPLICATE_APAAR", "DUPLICATE_APAAR_MATCH"]))
        .distinct()
        .all()
    )
    d_numerator = len(d_cases)
    d_rate = min(1.0, d_numerator / total_records)

    # -----------------------------------------------------------------------
    # A: Approval mismatches rate
    # Records where authority_status is FAILED or approval is invalid/unapproved
    # -----------------------------------------------------------------------
    a_mismatches = sum(
        1 for e in enrollments
        if (e.authority_status or "").upper() in ("FAIL", "FAILED")
    )
    a_numerator = a_mismatches
    a_rate = min(1.0, a_numerator / total_records)

    # -----------------------------------------------------------------------
    # T: Late submissions rate
    # Records tagged with late submission rules or post-deadline submissions
    # -----------------------------------------------------------------------
    t_issues = (
        db.query(ValidationIssue.enrollment_id)
        .filter(ValidationIssue.enrollment_id.in_(enrollment_ids))
        .filter(ValidationIssue.rule_code.in_(["RULE_L3_LATE_SUBMISSION", "RULE_L2_LATE_SUBMISSION_WITHOUT_REASON"]))
        .distinct()
        .all()
    )
    t_numerator = len(t_issues)
    t_rate = min(1.0, t_numerator / total_records)

    # -----------------------------------------------------------------------
    # Synthesise Q Score
    # -----------------------------------------------------------------------
    return calculate_data_quality_score(
        m_rate=m_rate,
        v_rate=v_rate,
        d_rate=d_rate,
        a_rate=a_rate,
        t_rate=t_rate,
        m_numerator=missing_field_count,
        m_denominator=total_required_fields_checked,
        v_numerator=v_numerator,
        v_denominator=total_records,
        d_numerator=d_numerator,
        d_denominator=total_records,
        a_numerator=a_numerator,
        a_denominator=total_records,
        t_numerator=t_numerator,
        t_denominator=total_records,
        total_records=total_records,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
    )


# ---------------------------------------------------------------------------
# Core Analytics Funnel & Metrics (Rule 11)
# ---------------------------------------------------------------------------

def compute_verification_funnel(
    db: Session,
    institution_id: Optional[str] = None,
) -> VerificationFunnelMetric:
    """Computes verification funnel counts directly from student enrollment records."""
    q = db.query(Enrollment)
    if institution_id:
        q = q.filter(Enrollment.institution_id == institution_id)

    records = q.all()
    total = len(records)
    confirmed = sum(1 for r in records if (r.status or "").upper() in OCCUPIED_STATUSES or (r.status or "").upper() == "VERIFIED")
    under_review = sum(1 for r in records if (r.status or "").upper() == "UNDER_REVIEW")
    provisional = sum(1 for r in records if (r.status or "").upper() == "PROVISIONAL")
    rejected = sum(1 for r in records if (r.status or "").upper() == "REJECTED")

    l1_pass = sum(1 for r in records if (r.identity_status or "").upper() in ("PASS", "PASSED"))
    l1_unavail = sum(1 for r in records if (r.identity_status or "").upper() in ("UNAVAILABLE", "SERVICE_UNAVAILABLE"))
    l1_fail = sum(1 for r in records if (r.identity_status or "").upper() in ("FAIL", "FAILED"))

    l2_pass = sum(1 for r in records if (r.authority_status or "").upper() in ("PASS", "PASSED"))
    l2_fail = sum(1 for r in records if (r.authority_status or "").upper() in ("FAIL", "FAILED"))

    l3_pass = sum(1 for r in records if (r.compliance_status or "").upper() in ("PASS", "PASSED"))
    l3_fail = sum(1 for r in records if (r.compliance_status or "").upper() in ("FAIL", "FAILED"))

    return VerificationFunnelMetric(
        total_submitted=total,
        confirmed_count=confirmed,
        under_review_count=under_review,
        provisional_count=provisional,
        rejected_count=rejected,
        l1_pass_count=l1_pass,
        l1_unavailable_count=l1_unavail,
        l1_fail_count=l1_fail,
        l2_pass_count=l2_pass,
        l2_fail_count=l2_fail,
        l3_pass_count=l3_pass,
        l3_fail_count=l3_fail,
    )


def compute_review_queue_summary(
    db: Session,
    institution_id: Optional[str] = None,
) -> ReviewQueueSummary:
    """Computes review queue metrics directly from review cases."""
    q = db.query(ReviewCase).filter(ReviewCase.status == "OPEN")
    if institution_id:
        q = q.filter(ReviewCase.institution_id == institution_id)

    cases = q.all()
    total_open = len(cases)
    high_pri = sum(1 for c in cases if (c.priority or 0.0) >= 70.0 or c.severity in ("HIGH", "CRITICAL"))
    dups = sum(1 for c in cases if "DUPLICATE" in (c.type or "").upper())
    cap_over = sum(1 for c in cases if "SEAT" in (c.type or "").upper() or "CAPACITY" in (c.type or "").upper())
    demo_mis = sum(1 for c in cases if "IDENTITY" in (c.type or "").upper() or "DEMOGRAPHIC" in (c.type or "").upper())
    unapproved = sum(1 for c in cases if "APPROVAL" in (c.type or "").upper() or "UNAPPROVED" in (c.type or "").upper())

    return ReviewQueueSummary(
        total_open_cases=total_open,
        high_priority_cases=high_pri,
        duplicate_match_cases=dups,
        capacity_overflow_cases=cap_over,
        demographic_mismatch_cases=demo_mis,
        unapproved_offering_cases=unapproved,
    )


def compute_program_seat_metrics(
    db: Session,
    institution_id: Optional[str] = None,
) -> List[ProgramSeatMetric]:
    """
    Computes per-program and per-category seat allocation & admission metrics.
    Rule 3: Quotas are strictly per category. Only CONFIRMED and ACTIVE consume seats.
    """
    app_query = db.query(ProgramApproval)
    if institution_id:
        app_query = app_query.filter(ProgramApproval.institution_id == institution_id)

    approvals = app_query.all()
    metrics: List[ProgramSeatMetric] = []

    for app in approvals:
        compliance = calculate_approval_seat_compliance(db, app.id)
        by_seat = compliance.get("by_seat_type", {})
        totals = compliance.get("totals", {})

        category_metrics: List[CategorySeatMetric] = []
        for st_name, m in by_seat.items():
            category_metrics.append(
                CategorySeatMetric(
                    category=st_name,
                    quota_type="SUPERNUMERARY" if "SUPERNUMERARY" in st_name else "REGULAR",
                    approved_intake=m.get("approved", 0),
                    confirmed_admissions=m.get("confirmed", 0) + m.get("active", 0),
                    provisional_admissions=m.get("provisional", 0),
                    utilization_percentage=float(m.get("utilisation_pct", 0.0)),
                    is_overfilled=(m.get("status") == STATUS_EXCEEDED),
                )
            )

        program_label = f"{app.programme} - {app.branch}"
        metrics.append(
            ProgramSeatMetric(
                program_id=app.id,
                program_name=program_label,
                total_approved_intake=totals.get("approved", 0),
                total_confirmed=totals.get("occupied", 0),
                utilization_percentage=float(totals.get("utilisation_pct", 0.0)),
                category_breakdown=category_metrics,
            )
        )

    return metrics


def get_system_overview(db: Session) -> SystemOverviewAnalytics:
    """
    Rule 11: National level system overview computed dynamically from database tables.
    """
    total_insts = db.query(Institution).count()
    active_insts = db.query(Institution).filter(Institution.status == "ACTIVE").count()
    total_progs = db.query(ProgramApproval).count()

    program_metrics = compute_program_seat_metrics(db)
    total_intake = sum(p.total_approved_intake for p in program_metrics)
    total_confirmed = sum(p.total_confirmed for p in program_metrics)
    utilization = (total_confirmed / total_intake * 100.0) if total_intake > 0 else 0.0

    funnel = compute_verification_funnel(db)
    review_queue = compute_review_queue_summary(db)

    return SystemOverviewAnalytics(
        total_institutions=total_insts,
        active_institutions=active_insts,
        total_approved_programs=total_progs,
        total_statutory_intake=total_intake,
        total_confirmed_students=total_confirmed,
        overall_intake_utilization=round(utilization, 1),
        funnel=funnel,
        review_queue=review_queue,
        program_metrics=program_metrics,
    )


def get_institution_dashboard(
    db: Session,
    institution_id: str,
) -> InstitutionDashboardAnalytics:
    """
    Rule 7 & Rule 11: Computes institution-specific dashboard analytics.
    Includes Risk-Priority Score (PART A) and Data-Quality Score (PART B).
    """
    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        # Fallback to look up by code
        inst = db.query(Institution).filter(Institution.code == institution_id).first()

    inst_id = inst.id if inst else institution_id
    inst_name = inst.name if inst else "Unknown Institution"
    inst_code = inst.code if inst else institution_id

    # Find latest approval
    latest_app = (
        db.query(ProgramApproval)
        .filter(ProgramApproval.institution_id == inst_id)
        .order_by(ProgramApproval.created_at.desc())
        .first()
    )

    order_num = latest_app.approval_ref if latest_app else None
    rule_ver = "AICTE_APH_2024_25_V1"

    program_metrics = compute_program_seat_metrics(db, institution_id=inst_id)
    total_intake = sum(p.total_approved_intake for p in program_metrics)
    total_confirmed = sum(p.total_confirmed for p in program_metrics)
    utilization = (total_confirmed / total_intake * 100.0) if total_intake > 0 else 0.0

    funnel = compute_verification_funnel(db, institution_id=inst_id)
    review_summary = compute_review_queue_summary(db, institution_id=inst_id)

    # Compute PART A and PART B
    risk_score = compute_risk_priority_score(db, inst_id)
    quality_score = compute_data_quality_score(db, inst_id)

    return InstitutionDashboardAnalytics(
        institution_id=inst_id,
        institution_name=inst_name,
        aicte_permanent_id=inst_code,
        approval_order_number=order_num,
        rule_version=rule_ver,
        total_approved_intake=total_intake,
        total_confirmed_students=total_confirmed,
        utilization_percentage=round(utilization, 1),
        funnel=funnel,
        programs=program_metrics,
        open_review_cases_count=review_summary.total_open_cases,
        risk_priority=risk_score,
        data_quality=quality_score,
    )


def get_programme_compliance_analytics(
    db: Session,
    institution_id: str,
    programme: str,
    academic_year: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Combines Risk-Priority Score (PART A) and Data-Quality Score (PART B)
    with seat compliance metrics for an institution-programme-year.
    """
    risk_priority = compute_risk_priority_score(
        db,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
    )

    data_quality = compute_data_quality_score(
        db,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
    )

    # Program seat compliance
    app = (
        db.query(ProgramApproval)
        .filter(ProgramApproval.institution_id == institution_id)
        .filter(ProgramApproval.programme == programme)
    )
    if academic_year:
        app = app.filter(ProgramApproval.academic_year == academic_year)
    approval_record = app.first()

    compliance = (
        calculate_approval_seat_compliance(db, approval_record.id)
        if approval_record
        else {"overall_status": "NO_APPROVAL", "by_seat_type": {}, "totals": {}}
    )

    return {
        "institution_id": institution_id,
        "programme": programme,
        "academic_year": academic_year,
        "risk_priority_score": risk_priority,
        "data_quality_score": data_quality,
        "seat_compliance": compliance,
        "review_priority_label": "review-priority score, not a probability of misconduct",
    }
