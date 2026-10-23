import uuid
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session

from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.seat import SeatAllocation
from backend.models.student import Student
from backend.models.enrollment import Enrollment
from backend.models.identity import IdentityCheck
from backend.models.duplicate import DuplicateCandidate
from backend.models.review import ReviewCase
from backend.models.validation import ValidationIssue


def verify_l1_identity(
    db: Session,
    student: Student,
    request_id: str,
    simulated_match: bool = True,
    simulated_available: bool = True,
) -> IdentityCheck:
    """
    L1 Verification: Simulated APAAR Adapter (MOCK_APAAR_V1).
    Rule 1: Always label MOCK_APAAR_V1.
    Rule 5: When unavailable, status is UNAVAILABLE, not auto-fail.
    """
    if not simulated_available:
        status = "UNAVAILABLE"
        exists = False
        name_match = False
        dob_match = False
    elif simulated_match:
        status = "PASS"
        exists = True
        name_match = True
        dob_match = True
    else:
        status = "FAIL"
        exists = True
        name_match = False
        dob_match = False

    check = IdentityCheck(
        student_id=student.id,
        request_id=request_id,
        source="MOCK_APAAR_V1",
        status=status,
        exists=exists,
        name_match=name_match,
        dob_match=dob_match,
        raw={
            "adapter": "MOCK_APAAR_V1",
            "simulated": True,
            "status": status,
        },
    )
    db.add(check)
    db.flush()
    return check


def verify_l2_authority(
    db: Session,
    approval_id: str,
) -> Tuple[bool, str]:
    """
    L2 Verification: Institutional Authority.
    Checks whether the program approval is FROZEN (immutable AICTE approved snapshot).
    """
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not approval:
        return False, "PROGRAM_APPROVAL_NOT_FOUND"
    if approval.status != ApprovalStatus.FROZEN:
        return False, "PROGRAM_APPROVAL_NOT_FROZEN"
    return True, "FROZEN_APPROVAL_VALIDATED"


def verify_l3_compliance(
    db: Session,
    enrollment: Enrollment,
) -> Tuple[bool, str]:
    """
    L3 Verification: Seat allocation & duplicate checks.
    Rule 3: Check seat capacity per seat_type.
    """
    # 1. Capacity check
    allocation = (
        db.query(SeatAllocation)
        .filter(
            SeatAllocation.approval_id == enrollment.approval_id,
            SeatAllocation.seat_type == enrollment.seat_type,
        )
        .first()
    )
    if not allocation:
        return False, f"SEAT_TYPE_NOT_ALLOCATED: {enrollment.seat_type}"

    # Count currently admitted / verified enrollments in this approval & seat_type
    enrolled_count = (
        db.query(Enrollment)
        .filter(
            Enrollment.approval_id == enrollment.approval_id,
            Enrollment.seat_type == enrollment.seat_type,
            Enrollment.status.in_(["PROVISIONAL", "ADMITTED", "VERIFIED"]),
            Enrollment.id != enrollment.id,
        )
        .count()
    )

    if enrolled_count >= allocation.approved_count:
        # Create validation issue & review case
        issue = ValidationIssue(
            enrollment_id=enrollment.id,
            rule_code="RULE_SEAT_OVERFLOW",
            severity="ERROR",
            message=f"Approved capacity {allocation.approved_count} exceeded for seat type {enrollment.seat_type}",
            status="OPEN",
        )
        db.add(issue)
        return False, "CAPACITY_EXCEEDED"

    return True, "SEAT_COMPLIANT"
