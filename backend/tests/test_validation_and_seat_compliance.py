from datetime import date, datetime, timezone
import pytest
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.rule_config import RuleSeverityConfig
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.security.crypto import create_jwt
from backend.services.seat_compliance import (
    STATUS_AT_LIMIT,
    STATUS_EXCEEDED,
    STATUS_NEAR_LIMIT,
    STATUS_NO_APPROVAL,
    STATUS_OK,
    calculate_approval_seat_compliance,
)
from backend.services.validation_service import (
    ALL_RULES,
    RULE_CATALOGUE_BY_CODE,
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_HIGH,
    SEVERITY_REGULATORY_ALERT,
    SEVERITY_WARNING,
    evaluate_admission_rules,
    generate_rule_catalogue_markdown,
    get_configured_severity,
)


@pytest.fixture
def compliance_setup(db_session: Session):
    """Sets up institution, frozen approval, and seat allocations."""
    now = datetime.now(timezone.utc)
    inst = Institution(code="1-COMP-01", name="National Engineering Institute", status="ACTIVE")
    db_session.add(inst)
    db_session.commit()

    approval = ProgramApproval(
        institution_id=inst.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-COMP-2024",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="admin-aicte",
    )
    db_session.add(approval)
    db_session.commit()

    alloc_reg = SeatAllocation(
        approval_id=approval.id,
        seat_type=SeatType.REGULAR,
        approved_count=120,
        rule_version="AICTE_APH_2024_25",
    )
    alloc_super = SeatAllocation(
        approval_id=approval.id,
        seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO,
        approved_count=15,
        rule_version="AICTE_APH_2024_25",
    )
    db_session.add_all([alloc_reg, alloc_super])
    db_session.commit()

    token = create_jwt({"sub": "admin-01", "email": "admin@aicte.gov.in", "role": "AICTE_ADMIN"})

    return {
        "inst": inst,
        "approval": approval,
        "alloc_reg": alloc_reg,
        "alloc_super": alloc_super,
        "token": token,
    }


# ---------------------------------------------------------------------------
# 1. Seat Compliance: 135 Admitted (120 Regular + 15 Supernumerary) -> OK
# ---------------------------------------------------------------------------

def test_seat_compliance_135_admitted_120_regular_15_supernumerary_ok(compliance_setup, db_session):
    """
    Explicit test:
    135 admitted = 120 regular + 15 supernumerary-category -> OK (AT_LIMIT).
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    now = datetime.now(timezone.utc)

    # Insert 120 regular confirmed students
    students_and_enrollments = []
    for i in range(120):
        st = Student(
            apaar_encrypted="enc",
            apaar_hash=f"hash_reg_{i}",
            apaar_masked=f"XXXX-XXXX-{i:04d}",
            name=f"Student Reg {i}",
            name_normalized=f"STUDENT REG {i}",
            dob=date(2005, 1, 1),
            gender="MALE",
        )
        db_session.add(st)
        db_session.flush()

        enroll = Enrollment(
            student_id=st.id,
            institution_id=inst.id,
            approval_id=approval.id,
            academic_year="2024-2025",
            seat_type="REGULAR",
            category="OPEN",
            admission_date=now,
            round="1",
            status="CONFIRMED",
            verified=True,
        )
        students_and_enrollments.append(enroll)

    # Insert 15 supernumerary confirmed students
    for i in range(15):
        st = Student(
            apaar_encrypted="enc",
            apaar_hash=f"hash_sup_{i}",
            apaar_masked=f"XXXX-XXXX-S{i:03d}",
            name=f"Student Sup {i}",
            name_normalized=f"STUDENT SUP {i}",
            dob=date(2005, 2, 1),
            gender="FEMALE",
        )
        db_session.add(st)
        db_session.flush()

        enroll = Enrollment(
            student_id=st.id,
            institution_id=inst.id,
            approval_id=approval.id,
            academic_year="2024-2025",
            seat_type="SUPERNUMERARY_FN_OCI_PIO",
            category="FN",
            admission_date=now,
            round="1",
            status="CONFIRMED",
            verified=True,
        )
        students_and_enrollments.append(enroll)

    db_session.add_all(students_and_enrollments)
    db_session.commit()

    report = calculate_approval_seat_compliance(db_session, approval.id)

    # Regular: 120 / 120 -> AT_LIMIT
    reg_data = report["by_seat_type"]["REGULAR"]
    assert reg_data["approved"] == 120
    assert reg_data["confirmed"] == 120
    assert reg_data["occupied"] == 120
    assert reg_data["available"] == 0
    assert reg_data["status"] == STATUS_AT_LIMIT

    # Supernumerary: 15 / 15 -> AT_LIMIT
    sup_data = report["by_seat_type"]["SUPERNUMERARY_FN_OCI_PIO"]
    assert sup_data["approved"] == 15
    assert sup_data["confirmed"] == 15
    assert sup_data["occupied"] == 15
    assert sup_data["available"] == 0
    assert sup_data["status"] == STATUS_AT_LIMIT

    # Overall totals: 135 admitted = 135 approved -> AT_LIMIT, NOT EXCEEDED!
    assert report["totals"]["occupied"] == 135
    assert report["totals"]["approved"] == 135
    assert report["overall_status"] == STATUS_AT_LIMIT


# ---------------------------------------------------------------------------
# 2. Seat Compliance: 121 Regular with 15 Supernumerary Unused -> EXCEEDED
# ---------------------------------------------------------------------------

def test_seat_compliance_121_regular_spare_supernumerary_must_not_absorb(compliance_setup, db_session):
    """
    Explicit test:
    121 regular-category with 15 supernumerary unused -> EXCEEDED.
    Spare supernumerary seats must NOT absorb regular students!
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    now = datetime.now(timezone.utc)

    # Insert 121 regular confirmed students (1 over capacity)
    for i in range(121):
        st = Student(
            apaar_encrypted="enc",
            apaar_hash=f"hash_excess_{i}",
            apaar_masked=f"XXXX-XXXX-E{i:03d}",
            name=f"Student Excess {i}",
            name_normalized=f"STUDENT EXCESS {i}",
            dob=date(2005, 1, 1),
            gender="MALE",
        )
        db_session.add(st)
        db_session.flush()

        enroll = Enrollment(
            student_id=st.id,
            institution_id=inst.id,
            approval_id=approval.id,
            academic_year="2024-2025",
            seat_type="REGULAR",
            category="OPEN",
            admission_date=now,
            round="1",
            status="CONFIRMED",
            verified=True,
        )
        db_session.add(enroll)

    # Supernumerary seats remain completely unused (0 admitted, 15 approved)
    db_session.commit()

    report = calculate_approval_seat_compliance(db_session, approval.id)

    # Regular category MUST BE EXCEEDED
    reg_data = report["by_seat_type"]["REGULAR"]
    assert reg_data["approved"] == 120
    assert reg_data["occupied"] == 121
    assert reg_data["status"] == STATUS_EXCEEDED, "Regular capacity 120 exceeded by 121 students!"

    # Supernumerary category has 15 available seats
    sup_data = report["by_seat_type"]["SUPERNUMERARY_FN_OCI_PIO"]
    assert sup_data["approved"] == 15
    assert sup_data["occupied"] == 0
    assert sup_data["available"] == 15
    assert sup_data["status"] == STATUS_OK

    # Overall program status MUST BE EXCEEDED despite spare supernumerary seats!
    assert report["overall_status"] == STATUS_EXCEEDED, (
        "Overall status must be EXCEEDED: Spare supernumerary seats must NOT absorb regular students!"
    )


# ---------------------------------------------------------------------------
# 3. Withdrawn Student Frees a Seat Test
# ---------------------------------------------------------------------------

def test_withdrawn_student_frees_a_seat(compliance_setup, db_session):
    """
    Explicit test:
    Withdrawn student frees a seat.
    Only CONFIRMED + ACTIVE are counted.
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    alloc_reg = compliance_setup["alloc_reg"]
    now = datetime.now(timezone.utc)

    # Set approved count to 1 for this test
    # (Since this approval was created in the fixture before freezing, update allocation in DRAFT if needed,
    # or create a single-seat dedicated approval)
    approval_1seat = ProgramApproval(
        institution_id=inst.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="CIVIL_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-CIVIL-01",
        version=1,
        status=ApprovalStatus.DRAFT,
    )
    db_session.add(approval_1seat)
    db_session.commit()

    alloc_civil = SeatAllocation(
        approval_id=approval_1seat.id,
        seat_type=SeatType.REGULAR,
        approved_count=1,
        rule_version="AICTE_2024_25",
    )
    db_session.add(alloc_civil)
    db_session.commit()

    approval_1seat.status = ApprovalStatus.FROZEN
    db_session.commit()

    # Create 1 student occupying the single seat
    st = Student(
        apaar_encrypted="enc",
        apaar_hash="hash_withdraw_01",
        apaar_masked="XXXX-XXXX-W001",
        name="Withdrawing Student",
        name_normalized="WITHDRAWING STUDENT",
        dob=date(2005, 1, 1),
        gender="MALE",
    )
    db_session.add(st)
    db_session.flush()

    enroll = Enrollment(
        student_id=st.id,
        institution_id=inst.id,
        approval_id=approval_1seat.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        round="1",
        status="CONFIRMED",
        verified=True,
    )
    db_session.add(enroll)
    db_session.commit()

    # 1. While CONFIRMED, seat is occupied (AT_LIMIT)
    report_active = calculate_approval_seat_compliance(db_session, approval_1seat.id)
    assert report_active["by_seat_type"]["REGULAR"]["occupied"] == 1
    assert report_active["by_seat_type"]["REGULAR"]["available"] == 0
    assert report_active["by_seat_type"]["REGULAR"]["status"] == STATUS_AT_LIMIT

    # 2. Student withdraws from institution
    enroll.status = "WITHDRAWN"
    db_session.commit()

    # 3. Re-run compliance: Withdrawn student freed the seat!
    report_freed = calculate_approval_seat_compliance(db_session, approval_1seat.id)
    assert report_freed["by_seat_type"]["REGULAR"]["occupied"] == 0
    assert report_freed["by_seat_type"]["REGULAR"]["available"] == 1
    assert report_freed["by_seat_type"]["REGULAR"]["status"] == STATUS_OK


# ---------------------------------------------------------------------------
# 4. Provisional Seats Tracked Separately Test
# ---------------------------------------------------------------------------

def test_provisional_seats_tracked_separately(compliance_setup, db_session):
    """
    Counts only CONFIRMED + ACTIVE.
    Provisional seats are reported separately and do not increment occupied.
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    now = datetime.now(timezone.utc)

    # Insert 1 CONFIRMED and 5 PROVISIONAL enrollments
    st1 = Student(
        apaar_encrypted="enc", apaar_hash="h1", apaar_masked="M1",
        name="Confirmed Student", name_normalized="CONFIRMED", dob=date(2005, 1, 1), gender="MALE",
    )
    db_session.add(st1)
    db_session.flush()

    e1 = Enrollment(
        student_id=st1.id, institution_id=inst.id, approval_id=approval.id,
        academic_year="2024-2025", seat_type="REGULAR", category="OPEN",
        admission_date=now, status="CONFIRMED",
    )
    db_session.add(e1)

    for i in range(5):
        st = Student(
            apaar_encrypted="enc", apaar_hash=f"hp_{i}", apaar_masked=f"MP_{i}",
            name=f"Provisional {i}", name_normalized=f"PROVISIONAL {i}", dob=date(2005, 1, 1), gender="FEMALE",
        )
        db_session.add(st)
        db_session.flush()

        e_prov = Enrollment(
            student_id=st.id, institution_id=inst.id, approval_id=approval.id,
            academic_year="2024-2025", seat_type="REGULAR", category="OPEN",
            admission_date=now, status="PROVISIONAL",
        )
        db_session.add(e_prov)

    db_session.commit()

    report = calculate_approval_seat_compliance(db_session, approval.id)
    reg_data = report["by_seat_type"]["REGULAR"]

    assert reg_data["confirmed"] == 1
    assert reg_data["provisional"] == 5
    assert reg_data["occupied"] == 1, "Only confirmed + active count towards occupied!"
    assert reg_data["available"] == 119


# ---------------------------------------------------------------------------
# 5. Configurable Severity Levels in Table Test
# ---------------------------------------------------------------------------

def test_rule_severity_configured_in_table(db_session):
    """
    Severity levels are configurable in the rule_severity_configs table.
    """
    rule_code = "RULE_L1_NAME_DOB_MISMATCH"
    # Default is WARNING
    default_sev = get_configured_severity(db_session, rule_code, SEVERITY_WARNING)
    assert default_sev == SEVERITY_WARNING

    # Override severity in DB table to CRITICAL
    cfg = RuleSeverityConfig(
        rule_code=rule_code,
        severity=SEVERITY_CRITICAL,
        is_active=True,
        description="Strict audit mode override",
    )
    db_session.add(cfg)
    db_session.commit()

    # Now resolver returns the customized severity
    custom_sev = get_configured_severity(db_session, rule_code, SEVERITY_WARNING)
    assert custom_sev == SEVERITY_CRITICAL


# ---------------------------------------------------------------------------
# 6. Verdict Logic Tests (Verified, Blocked, Under Review)
# ---------------------------------------------------------------------------

def test_verdict_logic_all_pass_verified(compliance_setup, db_session):
    """
    verified = (identity PASSED and authority PASS and compliance PASS).
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]

    context = {
        "record_ref": "PASS_RECORD_01",
        "apaar_id": "987654321015",
        "student_name": "Priya Patel",
        "dob": "2005-03-21",
        "admission_date": "2024-08-01",
        "programme": approval.programme,
        "branch": approval.branch,
        "academic_year": approval.academic_year,
        "campus": "MAIN",
        "shift": "FIRST",
        "approval": approval,
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": False,
        "fn_flag": False,
        "oci_flag": False,
        "seat_compliance": {"by_seat_type": {"REGULAR": {"status": STATUS_OK, "approved": 120, "occupied": 10}}},
    }

    report = evaluate_admission_rules(db_session, context)
    assert report.verified is True
    assert report.overall_verdict == "VERIFIED"
    assert report.blocks_commit is False
    assert report.requires_review is False


def test_verdict_logic_error_blocks_commit(compliance_setup, db_session):
    """
    Any ERROR blocks commit of that row.
    """
    approval = compliance_setup["approval"]

    # Contradictory flags: NRI and FN both True -> RULE_L3_CONTRADICTORY_FLAGS (ERROR)
    context = {
        "record_ref": "ERR_RECORD_01",
        "apaar_id": "987654321015",
        "student_name": "Priya Patel",
        "dob": "2005-03-21",
        "admission_date": "2024-08-01",
        "programme": approval.programme,
        "branch": approval.branch,
        "academic_year": approval.academic_year,
        "approval": approval,
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": True,
        "fn_flag": True,
        "seat_compliance": {"by_seat_type": {"REGULAR": {"status": STATUS_OK, "approved": 120, "occupied": 10}}},
    }

    report = evaluate_admission_rules(db_session, context)
    assert report.verified is False
    assert report.blocks_commit is True
    assert report.overall_verdict == "BLOCKED_ERROR"
    assert any(i.rule_code == "RULE_L3_CONTRADICTORY_FLAGS" for i in report.all_issues)


def test_verdict_logic_regulatory_alert_high_opens_review_case(compliance_setup, db_session):
    """
    REGULATORY_ALERT and HIGH open a review case and set UNDER_REVIEW.
    """
    approval = compliance_setup["approval"]

    # Capacity exceeded -> RULE_L3_CAPACITY_EXCEEDED (REGULATORY_ALERT)
    context = {
        "record_ref": "ALERT_RECORD_01",
        "apaar_id": "987654321015",
        "student_name": "Priya Patel",
        "dob": "2005-03-21",
        "admission_date": "2024-08-01",
        "programme": approval.programme,
        "branch": approval.branch,
        "academic_year": approval.academic_year,
        "approval": approval,
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": False,
        "fn_flag": False,
        "seat_compliance": {
            "by_seat_type": {
                "REGULAR": {"status": STATUS_EXCEEDED, "approved": 120, "occupied": 125}
            }
        },
    }

    report = evaluate_admission_rules(db_session, context)
    assert report.verified is False
    assert report.requires_review is True
    assert report.overall_verdict == "UNDER_REVIEW"
    assert any(i.severity == SEVERITY_REGULATORY_ALERT for i in report.all_issues)


# ---------------------------------------------------------------------------
# 7. Endpoints: GET /compliance and POST /recheck
# ---------------------------------------------------------------------------

def test_api_get_compliance_three_layers(client, compliance_setup, db_session):
    """
    GET /api/enrollments/{id}/compliance showing all three layers with their inputs and outputs.
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    token = compliance_setup["token"]
    now = datetime.now(timezone.utc)

    student = Student(
        apaar_encrypted="enc",
        apaar_hash="hash_api_comp",
        apaar_masked="XXXX-XXXX-9999",
        name="Demo Student",
        name_normalized="DEMO STUDENT",
        dob=date(2004, 5, 14),
        gender="MALE",
    )
    db_session.add(student)
    db_session.flush()

    enrollment = Enrollment(
        student_id=student.id,
        institution_id=inst.id,
        approval_id=approval.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        status="PROVISIONAL",
        verified=False,
    )
    db_session.add(enrollment)
    db_session.commit()

    res = client.get(
        f"/api/enrollments/{enrollment.id}/compliance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()

    # Three layers present
    assert "l1_identity" in data
    assert "l2_authority" in data
    assert "l3_compliance" in data

    # Inputs and outputs visible
    assert "inputs" in data["l1_identity"]
    assert "outputs" in data["l1_identity"]
    assert "inputs" in data["l2_authority"]
    assert "outputs" in data["l2_authority"]
    assert "inputs" in data["l3_compliance"]
    assert "outputs" in data["l3_compliance"]
    assert "overall_verdict" in data


def test_api_post_recheck_opens_case_and_updates_status(client, compliance_setup, db_session):
    """
    POST /api/enrollments/{id}/recheck re-runs rules, opens ReviewCase if needed.
    """
    approval = compliance_setup["approval"]
    inst = compliance_setup["inst"]
    token = compliance_setup["token"]
    now = datetime.now(timezone.utc)

    student = Student(
        apaar_encrypted="enc",
        apaar_hash="hash_api_recheck",
        apaar_masked="XXXX-XXXX-8888",
        name="Recheck Student",
        name_normalized="RECHECK STUDENT",
        dob=date(2004, 5, 14),
        gender="FEMALE",
    )
    db_session.add(student)
    db_session.flush()

    # Allocate under SUPERNUMERARY_FN_OCI_PIO without evidence_ref -> triggers REGULATORY_ALERT
    enrollment = Enrollment(
        student_id=student.id,
        institution_id=inst.id,
        approval_id=approval.id,
        academic_year="2024-2025",
        seat_type="SUPERNUMERARY_FN_OCI_PIO",
        category="FN",
        admission_date=now,
        status="PROVISIONAL",
        verified=False,
    )
    db_session.add(enrollment)
    db_session.commit()

    res = client.post(
        f"/api/enrollments/{enrollment.id}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["requires_review"] is True
    assert data["overall_verdict"] == "UNDER_REVIEW"

    # Verify ReviewCase created in database
    case = db_session.query(ReviewCase).filter(ReviewCase.enrollment_id == enrollment.id).first()
    assert case is not None
    assert case.type == "COMPLIANCE_REVIEW"
    assert case.severity == "HIGH"
    assert case.status == "OPEN"


# ---------------------------------------------------------------------------
# 8. Rule Catalogue Integrity Test
# ---------------------------------------------------------------------------

def test_generated_rule_catalogue_contains_all_rules():
    """
    Verifies that the generated rule catalogue markdown contains all registered rules.
    """
    catalogue_md = generate_rule_catalogue_markdown()
    assert len(ALL_RULES) >= 13

    for rule_cls in ALL_RULES:
        assert rule_cls.rule_code in catalogue_md, f"Rule '{rule_cls.rule_code}' missing from catalogue!"
        assert rule_cls.name in catalogue_md, f"Rule name '{rule_cls.name}' missing from catalogue!"
        assert rule_cls.default_severity in catalogue_md
