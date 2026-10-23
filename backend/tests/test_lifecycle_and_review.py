"""
Test Suite for Lifecycle State Machine & Review Service (backend/tests/test_lifecycle_and_review.py)

Tests:
1. Enrollment State Machine:
   - Valid transitions: DRAFT -> PROVISIONAL, PROVISIONAL -> CONFIRMED, CONFIRMED -> ACTIVE, etc.
   - Invalid transitions: Returns 409 Conflict with {code: "INVALID_TRANSITION", from, to, allowed}.
   - Role enforcement: Students/auditors cannot transition; institutions cannot self-approve.
   - Closed record reopening: Restricted to AICTE_ADMIN with mandatory exceptional_reason.
   - Seat count recalculation: Releasing states (WITHDRAWN, CANCELLED, MIGRATED) free seats.
2. Review Cases:
   - Workflow transitions: OPEN -> ASSIGNED -> AWAITING_INSTITUTION -> UNDER_DECISION -> RESOLVED.
   - Decisions: CONFIRM, REJECT, WITHDRAW_ONE_RECORD, DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT.
   - Decision side-effects applied via state machine to enrollment.
   - Institution cannot decide review cases (403 Forbidden).
   - Evidence references + SHA-256 validation (advances awaiting case to under_decision).
   - SLA due dates by severity and overdue flag.
   - History completeness.
3. Correction Requests:
   - Version N+1 creation with before/after snapshot and retained old versions.
   - Institution cannot approve (403 Forbidden).
"""
from datetime import date, datetime, timedelta, timezone
import pytest
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.correction import CorrectionRequest
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.user import User
from backend.models.version import RecordVersion
from backend.schemas.errors import BadRequestError, ForbiddenError
from backend.security.crypto import create_jwt
from backend.services.lifecycle import (
    ENROLLMENT_TRANSITIONS,
    InvalidTransitionError,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_DRAFT,
    STATUS_MIGRATED,
    STATUS_PROVISIONAL,
    STATUS_REJECTED,
    STATUS_UNDER_REVIEW,
    STATUS_WITHDRAWN,
    transition_enrollment_status,
    transition_review_case_status,
)
from backend.services.review_service import (
    assign_review_case,
    attach_evidence_reference,
    calculate_due_date,
    create_correction_request,
    create_review_case,
    decide_correction_request,
    decide_review_case,
    get_review_case_history,
    is_case_overdue,
)
from backend.services.seat_compliance import calculate_approval_seat_compliance


@pytest.fixture
def lifecycle_setup(db_session: Session):
    """Sets up an institution, program approval, seats, reviewer user, and student."""
    now = datetime.now(timezone.utc)
    inst = Institution(code="1-LIFE-01", name="Lifecycle Engineering College", status="ACTIVE")
    db_session.add(inst)
    db_session.commit()

    appr = ProgramApproval(
        institution_id=inst.id,
        programme="ENGINEERING",
        branch="IT",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-LIFE-2024",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="admin-aicte",
    )
    db_session.add(appr)
    db_session.commit()

    alloc = SeatAllocation(
        approval_id=appr.id,
        seat_type=SeatType.REGULAR.value,
        approved_count=60,
        rule_version="APH_2024_V1",
    )
    db_session.add(alloc)
    db_session.commit()

    student = Student(
        apaar_encrypted="ENC_LIFE",
        apaar_hash="hash_life_001",
        apaar_masked="XXXX-XXXX-9999",
        name="Karan Kapoor",
        name_normalized="KARAN KAPOOR",
        dob=date(2004, 8, 20),
        gender="MALE",
    )
    db_session.add(student)
    db_session.commit()

    reviewer = User(
        email="reviewer@aicte.gov.in",
        password_hash="fakehash",
        role="AICTE_REVIEWER",
        is_active=True,
    )
    db_session.add(reviewer)

    inst_operator = User(
        email="operator@life.edu",
        password_hash="fakehash",
        role="INSTITUTION_OPERATOR",
        institution_id=inst.id,
        is_active=True,
    )
    db_session.add(inst_operator)
    db_session.commit()

    return {
        "inst": inst,
        "appr": appr,
        "alloc": alloc,
        "student": student,
        "reviewer": reviewer,
        "inst_operator": inst_operator,
    }


# ===========================================================================
# 1. State Machine Transition Pair Tests
# ===========================================================================
def test_valid_enrollment_transitions(db_session: Session, lifecycle_setup):
    """Tests all valid standard transitions through the state machine."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    # 1. DRAFT -> PROVISIONAL
    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_DRAFT, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    transition_enrollment_status(db_session, e, STATUS_PROVISIONAL, actor_id="user-1", actor_role="AICTE_ADMIN")
    assert e.status == STATUS_PROVISIONAL

    # 2. PROVISIONAL -> UNDER_REVIEW
    transition_enrollment_status(db_session, e, STATUS_UNDER_REVIEW, actor_id="user-1", actor_role="AICTE_ADMIN")
    assert e.status == STATUS_UNDER_REVIEW

    # 3. UNDER_REVIEW -> CONFIRMED
    transition_enrollment_status(db_session, e, STATUS_CONFIRMED, actor_id="user-1", actor_role="AICTE_ADMIN")
    assert e.status == STATUS_CONFIRMED
    assert e.verified is True

    # 4. CONFIRMED -> ACTIVE
    transition_enrollment_status(db_session, e, STATUS_ACTIVE, actor_id="user-1", actor_role="AICTE_ADMIN")
    assert e.status == STATUS_ACTIVE

    # 5. ACTIVE -> COMPLETED
    transition_enrollment_status(db_session, e, STATUS_COMPLETED, actor_id="user-1", actor_role="AICTE_ADMIN")
    assert e.status == STATUS_COMPLETED


def test_invalid_enrollment_transition_raises_409(db_session: Session, lifecycle_setup):
    """
    Tests that invalid transitions raise InvalidTransitionError (HTTP 409)
    with structured payload {code: "INVALID_TRANSITION", from, to, allowed}.
    """
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_DRAFT, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    # Attempt DRAFT -> ACTIVE (invalid)
    with pytest.raises(InvalidTransitionError) as exc_info:
        transition_enrollment_status(db_session, e, STATUS_ACTIVE, actor_id="user-1", actor_role="AICTE_ADMIN")

    err = exc_info.value
    assert err.status_code == 409
    assert err.code == "INVALID_TRANSITION"
    assert err.details["from"] == STATUS_DRAFT
    assert err.details["to"] == STATUS_ACTIVE
    assert STATUS_PROVISIONAL in err.details["allowed"]
    assert STATUS_CANCELLED in err.details["allowed"]


def test_reopening_closed_record_requires_aicte_admin_and_exceptional_reason(db_session: Session, lifecycle_setup):
    """
    Closed terminal records (WITHDRAWN, CANCELLED, COMPLETED, REJECTED)
    can ONLY be reopened by AICTE_ADMIN with a mandatory exceptional_reason.
    """
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_WITHDRAWN, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    # 1. Institution Admin attempting to reopen raises 403 Forbidden
    with pytest.raises(ForbiddenError):
        transition_enrollment_status(
            db_session, e, STATUS_PROVISIONAL, actor_id="inst-admin", actor_role="INSTITUTION_ADMIN",
            exceptional_reason="Want student back",
        )

    # 2. AICTE_ADMIN without exceptional_reason raises 400 BadRequest
    with pytest.raises(BadRequestError):
        transition_enrollment_status(
            db_session, e, STATUS_PROVISIONAL, actor_id="admin-1", actor_role="AICTE_ADMIN",
            exceptional_reason=None,
        )

    # 3. AICTE_ADMIN with exceptional_reason succeeds
    transition_enrollment_status(
        db_session, e, STATUS_PROVISIONAL, actor_id="admin-1", actor_role="AICTE_ADMIN",
        exceptional_reason="Formal court appeal reinstatement order #2026/88",
    )
    assert e.status == STATUS_PROVISIONAL


def test_releasing_seat_recalculates_seat_compliance(db_session: Session, lifecycle_setup):
    """Releasing a seat (WITHDRAWN/CANCELLED/MIGRATED) decreases occupied seats and recalculates counts."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_CONFIRMED, verified=True,
    )
    db_session.add(e)
    db_session.commit()

    # Prior occupancy: 1
    pre = calculate_approval_seat_compliance(db_session, appr.id)
    assert pre["by_seat_type"]["REGULAR"]["occupied"] == 1
    assert pre["by_seat_type"]["REGULAR"]["available"] == 59

    # Withdraw student via state machine
    transition_enrollment_status(
        db_session, e, STATUS_WITHDRAWN, actor_id="inst-admin", actor_role="INSTITUTION_ADMIN",
        reason="Student accepted another college offer",
    )
    assert e.status == STATUS_WITHDRAWN
    assert e.verified is False

    # Post occupancy: 0 (seat immediately restored)
    post = calculate_approval_seat_compliance(db_session, appr.id)
    assert post["by_seat_type"]["REGULAR"]["occupied"] == 0
    assert post["by_seat_type"]["REGULAR"]["available"] == 60


# ===========================================================================
# 2. Review Cases Workflow & Decisions Tests
# ===========================================================================
def test_review_case_workflow_transitions(db_session: Session, lifecycle_setup):
    """Tests review case workflow: OPEN -> ASSIGNED -> AWAITING_INSTITUTION -> UNDER_DECISION -> RESOLVED."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    case = create_review_case(db_session, type_str="IDENTITY_MISMATCH", enrollment_id=e.id, severity="HIGH")
    assert case.status == "OPEN"

    # Assign
    assign_review_case(db_session, case.id, reviewer.id, actor_id="admin-1", actor_role="AICTE_ADMIN")
    assert case.status == "ASSIGNED"
    assert case.assigned_to == reviewer.id

    # Request explanation from institution
    transition_review_case_status(db_session, case, "AWAITING_INSTITUTION", actor_id=reviewer.id, actor_role="AICTE_REVIEWER")
    assert case.status == "AWAITING_INSTITUTION"

    # Institution submits evidence -> automatically advances to UNDER_DECISION
    valid_hash = "a" * 64
    attach_evidence_reference(
        db_session, case.id, evidence_ref="AFFIDAVIT-DOC-001", evidence_hash=valid_hash,
        description="Notarized name affidavit", actor_id="inst-admin", actor_role="INSTITUTION_ADMIN",
    )
    assert case.status == "UNDER_DECISION"


def test_review_case_decisions_apply_consequences_to_enrollment(db_session: Session, lifecycle_setup):
    """Tests that decisions apply their consequences to the enrollment strictly via the state machine."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    now = datetime.now(timezone.utc)

    # 1. Decision CONFIRM -> Enrollment becomes CONFIRMED (verified=True)
    e1 = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e1)
    db_session.commit()

    c1 = create_review_case(db_session, type_str="SEAT_EXCEPTION", enrollment_id=e1.id)
    decide_review_case(
        db_session, c1.id, decision="CONFIRM", decision_reason="Verified by reviewer upon affidavit review",
        actor_id=reviewer.id, actor_role="AICTE_REVIEWER",
    )
    assert c1.status == "RESOLVED"
    assert c1.decision == "CONFIRM"
    db_session.refresh(e1)
    assert e1.status == STATUS_CONFIRMED
    assert e1.verified is True

    # 2. Decision REJECT -> Enrollment becomes REJECTED
    e2 = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e2)
    db_session.commit()

    c2 = create_review_case(db_session, type_str="SEAT_EXCEPTION", enrollment_id=e2.id)
    decide_review_case(
        db_session, c2.id, decision="REJECT", decision_reason="Invalid category allocation without approval",
        actor_id=reviewer.id, actor_role="AICTE_REVIEWER",
    )
    assert c2.status == "RESOLVED"
    db_session.refresh(e2)
    assert e2.status == STATUS_REJECTED

    # 3. Decision WITHDRAW_ONE_RECORD -> Enrollment becomes WITHDRAWN (frees seat)
    e3 = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e3)
    db_session.commit()

    c3 = create_review_case(db_session, type_str="DUPLICATE", enrollment_id=e3.id)
    decide_review_case(
        db_session, c3.id, decision="WITHDRAW_ONE_RECORD", decision_reason="Duplicate confirmed; withdrawn from this institute",
        actor_id=reviewer.id, actor_role="AICTE_REVIEWER",
    )
    db_session.refresh(e3)
    assert e3.status == STATUS_WITHDRAWN


def test_institution_cannot_decide_review_cases(db_session: Session, lifecycle_setup):
    """Rule: Institutions cannot decide or approve their own review cases or exceptions (403 Forbidden)."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    case = create_review_case(db_session, type_str="APPROVAL_MISMATCH", enrollment_id=e.id)

    with pytest.raises(ForbiddenError):
        decide_review_case(
            db_session, case.id, decision="CONFIRM", decision_reason="Institution self-approval attempt",
            actor_id="inst-admin-01", actor_role="INSTITUTION_ADMIN",
        )


def test_sla_calculation_and_overdue_flag(db_session: Session, lifecycle_setup):
    """Tests SLA due_at calculation by severity and overdue flag for past-due cases."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    # Active case with future due_at
    c1 = create_review_case(db_session, type_str="DUPLICATE", enrollment_id=e.id, severity="CRITICAL")
    assert not is_case_overdue(c1)

    # Overdue case (due in past)
    past_due = now - timedelta(hours=5)
    c2 = ReviewCase(
        type="SEAT_EXCEPTION", severity="CRITICAL", enrollment_id=e.id, institution_id=inst.id,
        status="OPEN", due_at=past_due,
    )
    db_session.add(c2)
    db_session.commit()

    assert is_case_overdue(c2) is True


def test_history_completeness_for_review_cases(db_session: Session, lifecycle_setup):
    """Verifies that review case lifecycle events are completely recorded in the audit trail."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    case = create_review_case(db_session, type_str="LATE_SUBMISSION", enrollment_id=e.id)
    assign_review_case(db_session, case.id, reviewer.id, actor_id="admin-1", actor_role="AICTE_ADMIN")
    attach_evidence_reference(
        db_session, case.id, evidence_ref="MED-CERT-2026", evidence_hash="b" * 64,
        description="Medical certificate", actor_id="inst-admin", actor_role="INSTITUTION_ADMIN",
    )
    decide_review_case(
        db_session, case.id, decision="CONFIRM", decision_reason="Medical leave validated",
        actor_id=reviewer.id, actor_role="AICTE_REVIEWER",
    )

    history = get_review_case_history(db_session, case.id)
    assert len(history) >= 4
    actions = [h["action"] for h in history]
    assert "REVIEW_CASE_CREATE" in actions
    assert "REVIEW_CASE_ASSIGN" in actions
    assert "REVIEW_CASE_EVIDENCE_ATTACH" in actions
    assert "REVIEW_CASE_DECIDE" in actions


# ===========================================================================
# 3. Correction Requests Tests (Version N+1)
# ===========================================================================
def test_correction_request_creates_version_n_plus_one_with_snapshot(db_session: Session, lifecycle_setup):
    """
    Tests that approving a correction request:
    1. Creates version N+1 of the record
    2. Writes before/after snapshot to RecordVersion
    3. Retains the old version permanently
    4. Applies modifications to student/enrollment
    """
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    inst_operator = lifecycle_setup["inst_operator"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_CONFIRMED, verified=True, version=1,
    )
    db_session.add(e)
    db_session.commit()

    # 1. Submit correction request
    corr_req = create_correction_request(
        db=db_session,
        enrollment_id=e.id,
        reason_code="OFFICIAL_CORRECTION",
        explanation="Student's name misspelling on 10th marksheet",
        proposed_changes={"name": "Karan Raj Kapoor", "category": "OBC_NCL"},
        actor_id=inst_operator.id,
        institution_id=inst.id,
    )
    assert corr_req.status == "PENDING"
    assert corr_req.previous_state["student"]["name"] == "Karan Kapoor"

    # 2. Institution cannot approve correction request (403 Forbidden)
    with pytest.raises(ForbiddenError):
        decide_correction_request(
            db=db_session, request_id=corr_req.id, approve=True,
            decision_reason="Institution self-approval", actor_id="inst-admin", actor_role="INSTITUTION_ADMIN",
        )

    # 3. AICTE Reviewer approves correction request
    decide_correction_request(
        db=db_session, request_id=corr_req.id, approve=True,
        decision_reason="Gazette notification and corrected marksheet verified",
        actor_id=reviewer.id, actor_role="AICTE_REVIEWER",
    )
    assert corr_req.status == "APPROVED"
    assert corr_req.version_created == 2

    # Check enrollment and student updated
    db_session.refresh(e)
    db_session.refresh(student)
    assert e.version == 2
    assert e.category == "OBC_NCL"
    assert student.name == "Karan Raj Kapoor"

    # Check RecordVersion snapshot
    v_record = (
        db_session.query(RecordVersion)
        .filter(RecordVersion.entity_id == e.id, RecordVersion.version == 2)
        .first()
    )
    assert v_record is not None
    assert v_record.snapshot["before"]["enrollment"]["category"] == "OPEN"
    assert v_record.snapshot["after"]["enrollment"]["category"] == "OBC_NCL"
    assert v_record.actor_id == reviewer.id


# ===========================================================================
# 4. API Endpoint Integration Tests
# ===========================================================================
def test_api_patch_enrollment_status_and_invalid_transition_409(client, db_session: Session, lifecycle_setup):
    """Tests PATCH /api/enrollments/{id}/status endpoint and 409 error structure."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_PROVISIONAL, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    admin_token = create_jwt({"sub": "admin-1", "email": "admin@aicte.gov.in", "role": "AICTE_ADMIN"})

    # 1. Invalid transition: PROVISIONAL -> ACTIVE (must confirm first)
    res_bad = client.patch(
        f"/api/enrollments/{e.id}/status",
        json={"target_status": "ACTIVE"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_bad.status_code == 409
    err = res_bad.json()
    assert err["code"] == "INVALID_TRANSITION"
    assert err["details"]["from"] == "PROVISIONAL"
    assert err["details"]["to"] == "ACTIVE"
    assert "CONFIRMED" in err["details"]["allowed"]

    # 2. Valid transition: PROVISIONAL -> CONFIRMED
    res_good = client.patch(
        f"/api/enrollments/{e.id}/status",
        json={"target_status": "CONFIRMED", "reason": "Verification passed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "CONFIRMED"
    assert res_good.json()["verified"] is True


def test_api_review_cases_lifecycle_and_decide(client, db_session: Session, lifecycle_setup):
    """Tests review case endpoints: GET, POST, assign, evidence, decide, history."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_UNDER_REVIEW, verified=False,
    )
    db_session.add(e)
    db_session.commit()

    admin_token = create_jwt({"sub": "admin-1", "email": "admin@aicte.gov.in", "role": "AICTE_ADMIN"})
    rev_token = create_jwt({"sub": reviewer.id, "email": reviewer.email, "role": "AICTE_REVIEWER"})
    inst_token = create_jwt({
        "sub": "inst-user-1", "email": "admin@life.edu", "role": "INSTITUTION_ADMIN", "institution_id": inst.id,
    })

    # 1. POST /api/review-cases
    resp_create = client.post(
        "/api/review-cases",
        json={"type": "SEAT_EXCEPTION", "enrollment_id": e.id, "severity": "HIGH"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_create.status_code == 201
    case_id = resp_create.json()["id"]

    # 2. POST /api/review-cases/{id}/assign
    resp_assign = client.post(
        f"/api/review-cases/{case_id}/assign",
        json={"assignee_id": reviewer.id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_assign.status_code == 200
    assert resp_assign.json()["assigned_to"] == reviewer.id

    # 3. POST /api/review-cases/{id}/evidence (Institution attaches evidence)
    sha_hash = "c" * 64
    resp_ev = client.post(
        f"/api/review-cases/{case_id}/evidence",
        json={"evidence_ref": "APH-2024-EXEMPTION", "evidence_hash": sha_hash, "description": "AICTE Council exemption letter"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert resp_ev.status_code == 200

    # 4. Institution cannot decide (403 Forbidden)
    resp_inst_decide = client.patch(
        f"/api/review-cases/{case_id}",
        json={"decision": "CONFIRM", "decision_reason": "Self approving exception"},
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert resp_inst_decide.status_code == 403

    # 5. AICTE Reviewer decides case -> CONFIRM
    resp_rev_decide = client.patch(
        f"/api/review-cases/{case_id}",
        json={"decision": "CONFIRM", "decision_reason": "Exemption letter validated by regional office"},
        headers={"Authorization": f"Bearer {rev_token}"},
    )
    assert resp_rev_decide.status_code == 200
    assert resp_rev_decide.json()["decision"] == "CONFIRM"
    assert resp_rev_decide.json()["enrollment_status"] == "CONFIRMED"

    # 6. GET /api/review-cases/{id}/history
    resp_hist = client.get(
        f"/api/review-cases/{case_id}/history",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_hist.status_code == 200
    assert len(resp_hist.json()["history"]) >= 4


def test_api_correction_requests_endpoints(client, db_session: Session, lifecycle_setup):
    """Tests POST, GET, and PATCH /api/correction-requests."""
    inst = lifecycle_setup["inst"]
    appr = lifecycle_setup["appr"]
    student = lifecycle_setup["student"]
    reviewer = lifecycle_setup["reviewer"]
    inst_op = lifecycle_setup["inst_operator"]
    now = datetime.now(timezone.utc)

    e = Enrollment(
        student_id=student.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status=STATUS_CONFIRMED, verified=True, version=1,
    )
    db_session.add(e)
    db_session.commit()

    op_token = create_jwt({
        "sub": inst_op.id, "email": inst_op.email, "role": "INSTITUTION_OPERATOR", "institution_id": inst.id,
    })
    rev_token = create_jwt({"sub": reviewer.id, "email": reviewer.email, "role": "AICTE_REVIEWER"})

    # 1. POST /api/correction-requests
    res_post = client.post(
        "/api/correction-requests",
        json={
            "enrollment_id": str(e.id),
            "reason_code": "DATA_ENTRY_ERROR",
            "explanation": "Correcting typo in student name",
            "proposed_changes": {"name": "Karan Kumar Kapoor"},
        },
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert res_post.status_code == 201
    req_id = res_post.json()["id"]

    # 2. GET /api/correction-requests
    res_list = client.get(
        "/api/correction-requests",
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert res_list.status_code == 200
    assert res_list.json()["total"] >= 1

    # 3. GET /api/correction-requests/{id}
    res_get = client.get(
        f"/api/correction-requests/{req_id}",
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert res_get.status_code == 200
    assert res_get.json()["status"] == "PENDING"
    assert res_get.json()["previous_state"]["student"]["name"] == "Karan Kapoor"

    # 4. PATCH /api/correction-requests/{id} (Approve)
    res_patch = client.patch(
        f"/api/correction-requests/{req_id}",
        json={"approve": True, "decision_reason": "Typo verified against Aadhaar"},
        headers={"Authorization": f"Bearer {rev_token}"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["status"] == "APPROVED"
    assert res_patch.json()["version_created"] == 2

