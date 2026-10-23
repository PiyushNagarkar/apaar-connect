"""
Comprehensive Unit & Integration Tests for Analytics Service & Anomaly Detection.
Tests:
- PART A: Deterministic Risk-Priority Score R = w1*S + w2*D + w3*L + w4*C + w5*I
  - Default weights 0.30/0.25/0.15/0.10/0.20
  - Config table override weights
  - Weight renormalisation when component is unmeasurable (never treated as zero)
  - Identity coverage reporting (UNAVAILABLE excluded from numerator)
  - Regulatory label: 'review-priority score, not a probability of misconduct'
- PART B: Data-Quality Score Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))
  - 0-1 rates with explicit denominators stated
  - Floor at 0.0, ceiling at 100.0
  - Component rates alongside Q
- Anomaly Detection Scanners
- REST Endpoints under /api/analytics
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.rule_config import RiskScoreConfig
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import Submission
from backend.models.validation import ValidationIssue
from backend.services.anomaly_detection import (
    calculate_risk_priority_score,
    compute_risk_priority_score,
    compute_seat_exception_severity,
    compute_duplicate_severity,
    compute_late_submission_rate,
    compute_correction_rate,
    compute_identity_failure_rate,
    get_risk_score_weights,
    detect_seat_capacity_anomalies,
    detect_duplicate_spikes,
    scan_institution_anomalies,
    REVIEW_PRIORITY_LABEL,
    REASON_SEAT_EXCEEDED,
    REASON_CRITICAL_DUPLICATES,
    REASON_UNMEASURABLE_PREFIX,
)
from backend.services.analytics_service import (
    calculate_data_quality_score,
    compute_data_quality_score,
    get_system_overview,
    get_institution_dashboard,
    get_programme_compliance_analytics,
)


# ===========================================================================
# PART A: DETERMINISTIC RISK-PRIORITY SCORE UNIT TESTS
# ===========================================================================

def test_part_a_formula_with_all_components_measurable():
    """
    Tests R = 0.30*S + 0.25*D + 0.15*L + 0.10*C + 0.20*I
    Given S=50, D=20, L=10, C=30, I=40:
    R = 0.30*50 + 0.25*20 + 0.15*10 + 0.10*30 + 0.20*40
      = 15.0 + 5.0 + 1.5 + 3.0 + 8.0 = 32.5
    """
    res = calculate_risk_priority_score(
        s_value=50.0,
        d_value=20.0,
        l_value=10.0,
        c_value=30.0,
        i_value=40.0,
        coverage=0.95,
        rule_version="AICTE_APH_2024_25_V1",
    )

    assert res["score"] == 32.5
    assert res["label"] == "review-priority score, not a probability of misconduct"
    assert res["coverage"] == 0.95
    assert res["rule_version"] == "AICTE_APH_2024_25_V1"

    # Verify component breakdown
    comps = {c["name"]: c for c in res["components"]}
    assert comps["seat_exception_severity"]["value"] == 50.0
    assert comps["seat_exception_severity"]["weight"] == 0.30
    assert comps["seat_exception_severity"]["contribution"] == 15.0

    assert comps["duplicate_case_severity"]["value"] == 20.0
    assert comps["duplicate_case_severity"]["weight"] == 0.25
    assert comps["duplicate_case_severity"]["contribution"] == 5.0

    assert comps["late_submission_rate"]["value"] == 10.0
    assert comps["late_submission_rate"]["weight"] == 0.15
    assert comps["late_submission_rate"]["contribution"] == 1.5

    assert comps["correction_rate"]["value"] == 30.0
    assert comps["correction_rate"]["weight"] == 0.10
    assert comps["correction_rate"]["contribution"] == 3.0

    assert comps["identity_failure_rate"]["value"] == 40.0
    assert comps["identity_failure_rate"]["weight"] == 0.20
    assert comps["identity_failure_rate"]["contribution"] == 8.0


def test_part_a_renormalisation_when_component_is_unmeasurable():
    """
    Rule requirement:
    If a component is not measurable, return null and renormalise weights;
    never silently treat unknown as zero.

    Suppose I is None (unmeasurable).
    Original weights: S=0.30, D=0.25, L=0.15, C=0.10, I=0.20.
    Sum of measurable weights = 0.80.
    Renormalised weights:
    wS = 0.30/0.80 = 0.375
    wD = 0.25/0.80 = 0.3125
    wL = 0.15/0.80 = 0.1875
    wC = 0.10/0.80 = 0.125
    Given S=40, D=20, L=0, C=10, I=None:
    R = 0.375*40 + 0.3125*20 + 0.1875*0 + 0.125*10
      = 15.0 + 6.25 + 0 + 1.25 = 22.5
    """
    res = calculate_risk_priority_score(
        s_value=40.0,
        d_value=20.0,
        l_value=0.0,
        c_value=10.0,
        i_value=None,  # Not measurable!
        coverage=0.0,
    )

    assert res["score"] == 22.5
    comps = {c["name"]: c for c in res["components"]}

    # Unmeasurable component MUST return null for value, weight, contribution
    assert comps["identity_failure_rate"]["value"] is None
    assert comps["identity_failure_rate"]["weight"] is None
    assert comps["identity_failure_rate"]["contribution"] is None

    # Measurable components receive renormalised weights that sum to 1.0
    assert comps["seat_exception_severity"]["weight"] == 0.375
    assert comps["seat_exception_severity"]["contribution"] == 15.0

    assert comps["duplicate_case_severity"]["weight"] == 0.3125
    assert comps["duplicate_case_severity"]["contribution"] == 6.25

    assert comps["late_submission_rate"]["weight"] == 0.1875
    assert comps["late_submission_rate"]["contribution"] == 0.0

    assert comps["correction_rate"]["weight"] == 0.125
    assert comps["correction_rate"]["contribution"] == 1.25

    # Check reason codes include component unmeasurable notice
    assert any("IDENTITY_FAILURE_RATE" in r for r in res["reason_codes"])


def test_part_a_multiple_unmeasurable_components():
    """
    When multiple components are None (e.g. only S and D measurable):
    Original weights: S=0.30, D=0.25 (sum = 0.55).
    wS = 0.30 / 0.55 = 0.54545...
    wD = 0.25 / 0.55 = 0.45454...
    Given S=100, D=50:
    R = 0.54545*100 + 0.45454*50 = 54.55 + 22.73 = 77.27
    """
    res = calculate_risk_priority_score(
        s_value=100.0,
        d_value=50.0,
        l_value=None,
        c_value=None,
        i_value=None,
        coverage=None,
    )

    assert res["score"] == pytest.approx(77.27, abs=0.05)
    comps = {c["name"]: c for c in res["components"]}
    assert comps["seat_exception_severity"]["value"] == 100.0
    assert comps["duplicate_case_severity"]["value"] == 50.0
    assert comps["late_submission_rate"]["value"] is None
    assert comps["correction_rate"]["value"] is None
    assert comps["identity_failure_rate"]["value"] is None


def test_part_a_all_components_unmeasurable_returns_none_score():
    """
    If no components can be measured, score must be None (never silently 0).
    """
    res = calculate_risk_priority_score(
        s_value=None,
        d_value=None,
        l_value=None,
        c_value=None,
        i_value=None,
        coverage=None,
    )
    assert res["score"] is None
    for c in res["components"]:
        assert c["value"] is None
        assert c["weight"] is None
        assert c["contribution"] is None


def test_part_a_config_table_custom_weights(db_session: Session):
    """
    Verify weights are loaded from risk_score_configs table.
    """
    custom_cfg = RiskScoreConfig(
        rule_version="CUSTOM_2025_WEIGHTS",
        weight_s=0.50,
        weight_d=0.20,
        weight_l=0.10,
        weight_c=0.10,
        weight_i=0.10,
        is_active=True,
    )
    db_session.add(custom_cfg)
    db_session.commit()

    weights = get_risk_score_weights(db_session, "CUSTOM_2025_WEIGHTS")
    assert weights["weight_s"] == 0.50
    assert weights["weight_d"] == 0.20

    res = calculate_risk_priority_score(
        s_value=100.0,
        d_value=0.0,
        l_value=0.0,
        c_value=0.0,
        i_value=0.0,
        coverage=1.0,
        weights=weights,
        rule_version="CUSTOM_2025_WEIGHTS",
    )
    # 0.50 * 100 = 50.0
    assert res["score"] == 50.0


# ===========================================================================
# PART B: DATA-QUALITY SCORE UNIT TESTS
# ===========================================================================

def test_part_b_formula_perfect_data_quality():
    """
    When M=0, V=0, D=0, A=0, T=0 -> Q = 100.0 (Grade: EXCELLENT).
    """
    res = calculate_data_quality_score(
        m_rate=0.0,
        v_rate=0.0,
        d_rate=0.0,
        a_rate=0.0,
        t_rate=0.0,
        total_records=100,
    )
    assert res["score"] == 100.0
    assert res["grade"] == "EXCELLENT"
    assert res["formula"] == "Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))"

    # Verify each denominator is stated
    comps = res["components"]
    for sym, key in [
        ("M", "missing_required_fields"),
        ("V", "unresolved_validation_errors"),
        ("D", "unresolved_duplicate_cases"),
        ("A", "approval_mismatches"),
        ("T", "late_submissions"),
    ]:
        assert comps[key]["symbol"] == sym
        assert "denominator_description" in comps[key]
        assert comps[key]["rate"] == 0.0
        assert comps[key]["penalty"] == 0.0


def test_part_b_formula_with_defects_and_penalties():
    """
    Given:
    M = 0.10 (penalty = 35 * 0.10 = 3.5)
    V = 0.20 (penalty = 25 * 0.20 = 5.0)
    D = 0.05 (penalty = 20 * 0.05 = 1.0)
    A = 0.10 (penalty = 10 * 0.10 = 1.0)
    T = 0.20 (penalty = 10 * 0.20 = 2.0)
    Total deductions = 3.5 + 5.0 + 1.0 + 1.0 + 2.0 = 12.5
    Q = 100 - 12.5 = 87.5 (Grade: GOOD)
    """
    res = calculate_data_quality_score(
        m_rate=0.10,
        v_rate=0.20,
        d_rate=0.05,
        a_rate=0.10,
        t_rate=0.20,
        m_numerator=70,
        m_denominator=700,
        v_numerator=20,
        v_denominator=100,
        d_numerator=5,
        d_denominator=100,
        a_numerator=10,
        a_denominator=100,
        t_numerator=20,
        t_denominator=100,
        total_records=100,
    )
    assert res["score"] == 87.5
    assert res["grade"] == "GOOD"

    comps = res["components"]
    assert comps["missing_required_fields"]["penalty"] == 3.5
    assert comps["unresolved_validation_errors"]["penalty"] == 5.0
    assert comps["unresolved_duplicate_cases"]["penalty"] == 1.0
    assert comps["approval_mismatches"]["penalty"] == 1.0
    assert comps["late_submissions"]["penalty"] == 2.0


def test_part_b_floor_at_zero():
    """
    When defects exceed 100 points, Q must floor at exactly 0.0.
    """
    res = calculate_data_quality_score(
        m_rate=1.0,  # -35
        v_rate=1.0,  # -25
        d_rate=1.0,  # -20
        a_rate=1.0,  # -10
        t_rate=1.0,  # -10
        total_records=10,
    )
    # 100 - 100 = 0.0
    assert res["score"] == 0.0
    assert res["grade"] == "POOR"


# ===========================================================================
# DATABASE INTEGRATION TESTS (PART A & PART B ON DB)
# ===========================================================================

def _setup_test_institution_and_records(db_session: Session) -> str:
    now = datetime.now(timezone.utc)

    # 1. Create Institution
    inst = Institution(id="INST-TEST-ANALYTICS", code="TEST-001", name="National Tech Institute")
    db_session.add(inst)
    db_session.commit()

    # 2. Create Frozen Approval with 2 Categories
    app = ProgramApproval(
        id="APP-TEST-CSE",
        institution_id=inst.id,
        programme="ENGINEERING",
        branch="COMPUTER_SCIENCE",
        academic_year="2024-2025",
        approval_ref="AICTE/TEST/2024/001",
        version=1,
        status=ApprovalStatus.FROZEN,
    )
    db_session.add(app)
    db_session.commit()

    # Allocations: REGULAR approved=2, SUPERNUMERARY_FN_OCI_PIO approved=1
    alloc1 = SeatAllocation(
        approval_id=app.id,
        seat_type=SeatType.REGULAR,
        approved_count=2,
        rule_version="AICTE_APH_2024_25_V1",
    )
    alloc2 = SeatAllocation(
        approval_id=app.id,
        seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO,
        approved_count=1,
        rule_version="AICTE_APH_2024_25_V1",
    )
    db_session.add_all([alloc1, alloc2])
    db_session.commit()

    # 3. Create Students and Enrollments
    # Student 1: Confirmed REGULAR
    s1 = Student(
        id="STU-001",
        apaar_encrypted="enc1",
        apaar_hash="hash1",
        apaar_masked="XXXX-XXXX-0001",
        name="Student One",
        name_normalized="STUDENT ONE",
        dob=datetime(2005, 1, 1).date(),
        gender="M",
    )
    db_session.add(s1)
    db_session.commit()

    e1 = Enrollment(
        id="ENR-001",
        student_id=s1.id,
        institution_id=inst.id,
        approval_id=app.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        status="CONFIRMED",
        identity_status="PASS",
        authority_status="PASS",
        compliance_status="PASS",
        verified=True,
        version=1,
    )

    # Student 2: Confirmed REGULAR
    s2 = Student(
        id="STU-002",
        apaar_encrypted="enc2",
        apaar_hash="hash2",
        apaar_masked="XXXX-XXXX-0002",
        name="Student Two",
        name_normalized="STUDENT TWO",
        dob=datetime(2005, 2, 2).date(),
        gender="F",
    )
    db_session.add(s2)
    db_session.commit()

    e2 = Enrollment(
        id="ENR-002",
        student_id=s2.id,
        institution_id=inst.id,
        approval_id=app.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        status="CONFIRMED",
        identity_status="PASS",
        authority_status="PASS",
        compliance_status="PASS",
        verified=True,
        version=1,
    )

    # Student 3: Exceeds Capacity! (3 confirmed in REGULAR where approved=2)
    s3 = Student(
        id="STU-003",
        apaar_encrypted="enc3",
        apaar_hash="hash3",
        apaar_masked="XXXX-XXXX-0003",
        name="Student Three",
        name_normalized="STUDENT THREE",
        dob=datetime(2005, 3, 3).date(),
        gender="M",
    )
    db_session.add(s3)
    db_session.commit()

    e3 = Enrollment(
        id="ENR-003",
        student_id=s3.id,
        institution_id=inst.id,
        approval_id=app.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        status="CONFIRMED",
        identity_status="FAIL",  # Failed identity check
        authority_status="PASS",
        compliance_status="FAIL",
        verified=False,
        version=1,
    )
    db_session.add_all([e1, e2, e3])
    db_session.commit()

    # Add open critical duplicate review case for Student 3
    rev_case = ReviewCase(
        id="CASE-001",
        type="DUPLICATE_MATCH",
        severity="CRITICAL",
        priority=85.0,
        enrollment_id=e3.id,
        institution_id=inst.id,
        status="OPEN",
    )
    db_session.add(rev_case)
    db_session.commit()
    return inst.id


def test_database_backed_part_a_and_part_b(db_session: Session):
    """
    Sets up synthetic institution, approvals, allocations, and enrollments
    to test database-backed compute_risk_priority_score and compute_data_quality_score.
    """
    inst_id = _setup_test_institution_and_records(db_session)

    # --- Test PART A (Risk-Priority Score from DB) ---
    risk_res = compute_risk_priority_score(
        db_session,
        institution_id=inst_id,
        programme="ENGINEERING",
        academic_year="2024-2025",
    )
    assert risk_res["score"] is not None
    assert risk_res["score"] > 0
    assert risk_res["label"] == "review-priority score, not a probability of misconduct"
    assert "SEAT_CAPACITY_EXCEEDED" in risk_res["reason_codes"]

    # Component S should be > 0 because REGULAR is 3/2 (EXCEEDED)
    comps = {c["name"]: c for c in risk_res["components"]}
    assert comps["seat_exception_severity"]["value"] > 0

    # Component D should be > 0 because of the open critical duplicate case
    assert comps["duplicate_case_severity"]["value"] > 0

    # Component I: 2 passed, 1 failed -> failure rate = 1/3 = 33.33%
    assert comps["identity_failure_rate"]["value"] == pytest.approx(33.33, abs=0.5)
    assert risk_res["coverage"] == 1.0  # All 3 were available (2 pass + 1 fail)

    # --- Test PART B (Data-Quality Score from DB) ---
    dq_res = compute_data_quality_score(
        db_session,
        institution_id=inst_id,
        programme="ENGINEERING",
        academic_year="2024-2025",
    )
    assert dq_res["score"] < 100.0  # Deductions from duplicate case
    assert dq_res["total_records_evaluated"] == 3
    dq_comps = dq_res["components"]
    assert dq_comps["unresolved_duplicate_cases"]["numerator"] >= 1
    assert dq_comps["unresolved_duplicate_cases"]["denominator"] == 3
    assert dq_comps["unresolved_duplicate_cases"]["penalty"] > 0


def test_anomaly_detection_scanners(db_session: Session):
    """
    Tests detect_seat_capacity_anomalies, detect_duplicate_spikes, and scan_institution_anomalies.
    """
    inst_id = _setup_test_institution_and_records(db_session)
    seat_anomalies = detect_seat_capacity_anomalies(db_session, institution_id=inst_id)
    assert len(seat_anomalies) >= 1
    assert seat_anomalies[0]["status"] == "EXCEEDED"

    scan_res = scan_institution_anomalies(db_session, institution_id=inst_id)
    assert scan_res["institution_id"] == inst_id
    assert scan_res["anomaly_count"] >= 1
    assert scan_res["review_priority_label"] == REVIEW_PRIORITY_LABEL


# ===========================================================================
# REST API ENDPOINT TESTS
# ===========================================================================

def test_api_analytics_endpoints(client, db_session: Session):
    """
    Tests REST endpoints:
    - GET /api/analytics/overview
    - GET /api/analytics/institution/{institution_id}
    - GET /api/analytics/risk-priority
    - GET /api/analytics/data-quality
    - GET /api/analytics/anomalies
    """
    inst_id = _setup_test_institution_and_records(db_session)

    # 1. Overview
    resp_overview = client.get("/api/analytics/overview", headers={"X-Mock-Role": "AICTE_ADMIN"})
    assert resp_overview.status_code == 200
    overview_data = resp_overview.json()
    assert "total_institutions" in overview_data
    assert "synthetic_notice" in overview_data

    # 2. Institution Dashboard
    resp_inst = client.get(
        f"/api/analytics/institution/{inst_id}",
        headers={"X-Mock-Role": "AICTE_ADMIN", "X-Mock-Institution-Id": inst_id},
    )
    assert resp_inst.status_code == 200
    inst_data = resp_inst.json()
    assert inst_data["institution_id"] == inst_id
    assert "programs" in inst_data

    # 3. Risk-Priority Score (PART A)
    resp_risk = client.get(
        f"/api/analytics/risk-priority?institution_id={inst_id}&programme=ENGINEERING&academic_year=2024-2025",
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert resp_risk.status_code == 200
    risk_data = resp_risk.json()
    assert "score" in risk_data
    assert "components" in risk_data
    assert risk_data["label"] == "review-priority score, not a probability of misconduct"
    assert len(risk_data["components"]) == 5


    # 4. Data-Quality Score (PART B)
    resp_dq = client.get(
        f"/api/analytics/data-quality?institution_id={inst_id}&academic_year=2024-2025",
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert resp_dq.status_code == 200
    dq_data = resp_dq.json()
    assert "score" in dq_data
    assert "grade" in dq_data
    assert "components" in dq_data
    assert "missing_required_fields" in dq_data["components"]

    # 5. Anomalies Scan
    resp_anom = client.get(
        f"/api/analytics/anomalies?institution_id={inst_id}",
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert resp_anom.status_code == 200
    anom_data = resp_anom.json()
    assert "seat_anomalies" in anom_data
