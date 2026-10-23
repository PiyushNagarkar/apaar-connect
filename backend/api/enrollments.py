"""
Enrollment and Admission Endpoints protected by institution_scope and RBAC.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enrollment import Enrollment
from backend.schemas.errors import AppException, NotFoundError
from backend.security.authz import (
    UserPrincipal,
    require_authenticated_user,
    require_roles,
    require_permission,
    institution_scope,
    InstitutionScope,
    ForbiddenError,
)
from backend.security.permissions import (
    ACTION_ENROLLMENT_READ,
    ACTION_ENROLLMENT_WRITE,
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_AUDITOR,
)

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


class CreateEnrollmentRequest(BaseModel):
    student_id: str
    approval_id: str
    academic_year: str
    seat_type: str
    category: str


@router.get("/{enrollment_id}")
def get_enrollment(
    enrollment_id: str,
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/enrollments/{enrollment_id}:
    Protected by institution_scope.
    Institution users cannot access enrollments belonging to another institution (raises 403).
    """
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment with id '{enrollment_id}' was not found.")

    # Rule 7 & Acceptance check: Enforce institution scope
    # If operator from Institution A accesses Institution B -> ForbiddenError (403)
    scope.validate_access(enrollment.institution_id)

    return {
        "id": enrollment.id,
        "student_id": enrollment.student_id,
        "institution_id": enrollment.institution_id,
        "academic_year": enrollment.academic_year,
        "seat_type": enrollment.seat_type,
        "category": enrollment.category,
        "status": enrollment.status,
        "verified": enrollment.verified,
    }


@router.post("", status_code=201)
def create_enrollment(
    payload: CreateEnrollmentRequest,
    scope: InstitutionScope = Depends(institution_scope),
    user: UserPrincipal = Depends(require_permission(ACTION_ENROLLMENT_WRITE)),
    db: Session = Depends(get_db),
):
    """
    POST /api/enrollments:
    Protected by require_permission(ACTION_ENROLLMENT_WRITE).
    Auditor attempting a write will receive 403 Forbidden.
    Institution users automatically use their scoped institution_id.
    """
    from datetime import datetime, timezone

    # Never trust institution_id from request body for institution users
    inst_id = scope.user.institution_id if scope.is_institution_user else "INST-GLOBAL-DEFAULT"

    enrollment = Enrollment(
        student_id=payload.student_id,
        institution_id=inst_id,
        approval_id=payload.approval_id,
        academic_year=payload.academic_year,
        seat_type=payload.seat_type,
        category=payload.category,
        admission_date=datetime.now(timezone.utc),
        round="1",
        status="PROVISIONAL",
        verified=False,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return {"id": enrollment.id, "status": enrollment.status, "institution_id": enrollment.institution_id}


@router.get("/{enrollment_id}/compliance")
async def get_enrollment_compliance(
    enrollment_id: str,
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/enrollments/{id}/compliance:
    Shows all three verification layers (L1 Identity, L2 Authority, L3 Compliance)
    with their detailed inputs, outputs, triggered rules, and overall verdict.
    """
    from backend.models.student import Student
    from backend.models.approval import ProgramApproval
    from backend.models.identity import IdentityCheck
    from backend.services.seat_compliance import calculate_approval_seat_compliance
    from backend.services.validation_service import evaluate_admission_rules
    from backend.security.crypto import decrypt_apaar

    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment with id '{enrollment_id}' was not found.")

    scope.validate_access(enrollment.institution_id)

    student = db.query(Student).filter(Student.id == enrollment.student_id).first()
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == enrollment.approval_id).first()
    seat_comp = calculate_approval_seat_compliance(db, enrollment.approval_id) if enrollment.approval_id else {}

    raw_apaar = decrypt_apaar(student.apaar_encrypted) if (student and student.apaar_encrypted and student.apaar_encrypted != "NONE") else None

    # Fetch latest identity check if available
    latest_id_check = None
    if student:
        latest_id_check = (
            db.query(IdentityCheck)
            .filter(IdentityCheck.student_id == student.id)
            .order_by(IdentityCheck.created_at.desc())
            .first()
        )

    context = {
        "enrollment_id": str(enrollment.id),
        "record_ref": str(enrollment.id),
        "institution_id": str(enrollment.institution_id),
        "student_id": str(student.id) if student else None,
        "student_name": student.name if student else "",
        "dob": student.dob.isoformat() if (student and student.dob) else "",
        "apaar_id": raw_apaar,
        "admission_date": enrollment.admission_date,
        "programme": approval.programme if approval else "",
        "branch": approval.branch if approval else "",
        "academic_year": enrollment.academic_year,
        "campus": approval.campus if approval else "MAIN",
        "shift": approval.shift if approval else "FIRST",
        "seat_type": enrollment.seat_type,
        "category": enrollment.category,
        "nri_flag": True if (enrollment.category == "NRI" or enrollment.seat_type == "NRI") else False,
        "fn_flag": True if (enrollment.category in ("FN", "FOREIGN_NATIONAL") or "FN" in enrollment.seat_type) else False,
        "oci_flag": True if enrollment.category in ("OCI", "PIO") else False,
        "seat_compliance": seat_comp,
        "l1_result": latest_id_check,
        "evidence_ref": getattr(enrollment, "evidence_ref", None),
        "identity_status": getattr(enrollment, "identity_status", None),
    }

    report = evaluate_admission_rules(db, context)
    dump = report.model_dump()
    dump["overall_status"] = "PROVISIONAL" if (enrollment.status == "PROVISIONAL" and not report.verified) else report.overall_verdict
    dump["layer_1_identity"] = report.l1_identity.model_dump()
    dump["layer_2_authority"] = report.l2_authority.model_dump()
    dump["layer_3_compliance"] = report.l3_compliance.model_dump()
    if enrollment.identity_status == "UNAVAILABLE":
        dump["layer_1_identity"]["status"] = "UNAVAILABLE"
    return dump


@router.post("/{enrollment_id}/recheck")
async def recheck_enrollment_compliance(
    enrollment_id: str,
    user: UserPrincipal = Depends(require_permission(ACTION_ENROLLMENT_WRITE)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/enrollments/{id}/recheck:
    Re-runs all three layer validation rules against the current database state.
    Updates verified flag and status, opens a ReviewCase if REGULATORY_ALERT or HIGH,
    and logs an AuditEvent.
    """
    from backend.models.student import Student
    from backend.models.approval import ProgramApproval
    from backend.models.identity import IdentityCheck
    from backend.models.review import ReviewCase
    from backend.models.validation import ValidationIssue
    from backend.services.seat_compliance import calculate_approval_seat_compliance
    from backend.services.validation_service import evaluate_admission_rules
    from backend.services.identity_adapter import get_identity_provider
    from backend.services.audit import record_audit_event
    from backend.security.crypto import decrypt_apaar

    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment with id '{enrollment_id}' was not found.")

    scope.validate_access(enrollment.institution_id)

    student = db.query(Student).filter(Student.id == enrollment.student_id).first()
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == enrollment.approval_id).first()
    seat_comp = calculate_approval_seat_compliance(db, enrollment.approval_id) if enrollment.approval_id else {}

    raw_apaar = decrypt_apaar(student.apaar_encrypted) if (student and student.apaar_encrypted and student.apaar_encrypted != "NONE") else None

    # Perform active identity check re-verification
    provider = get_identity_provider()
    l1_res = None
    if raw_apaar and student:
        l1_res = await provider.verify(
            request_id=f"recheck-{enrollment.id[:8]}",
            apaar_id=raw_apaar,
            student_name=student.name,
            date_of_birth=student.dob.isoformat() if student.dob else "",
        )

    context = {
        "enrollment_id": str(enrollment.id),
        "record_ref": str(enrollment.id),
        "institution_id": str(enrollment.institution_id),
        "student_id": str(student.id) if student else None,
        "student_name": student.name if student else "",
        "dob": student.dob.isoformat() if (student and student.dob) else "",
        "apaar_id": raw_apaar,
        "admission_date": enrollment.admission_date,
        "programme": approval.programme if approval else "",
        "branch": approval.branch if approval else "",
        "academic_year": enrollment.academic_year,
        "campus": approval.campus if approval else "MAIN",
        "shift": approval.shift if approval else "FIRST",
        "approval": approval,
        "seat_type": enrollment.seat_type,
        "category": enrollment.category,
        "nri_flag": True if (enrollment.category == "NRI" or enrollment.seat_type == "NRI") else False,
        "fn_flag": True if (enrollment.category in ("FN", "FOREIGN_NATIONAL") or "FN" in enrollment.seat_type) else False,
        "oci_flag": True if enrollment.category in ("OCI", "PIO") else False,
        "seat_compliance": seat_comp,
        "l1_result": l1_res,
        "evidence_ref": getattr(enrollment, "evidence_ref", None),
    }


    report = evaluate_admission_rules(db, context)

    # Update enrollment attributes
    enrollment.identity_status = report.l1_identity.status
    enrollment.authority_status = report.l2_authority.status
    enrollment.compliance_status = report.l3_compliance.status
    enrollment.verified = report.verified

    if report.verified:
        enrollment.status = "CONFIRMED"
    elif report.requires_review:
        enrollment.status = "UNDER_REVIEW"
        # Check if an open ReviewCase already exists
        existing_case = (
            db.query(ReviewCase)
            .filter(ReviewCase.enrollment_id == enrollment.id, ReviewCase.status == "OPEN")
            .first()
        )
        if not existing_case:
            case = ReviewCase(
                type="COMPLIANCE_REVIEW",
                severity="HIGH",
                priority=80.0,
                enrollment_id=enrollment.id,
                status="OPEN",
                evidence={"report": report.model_dump()},
            )
            db.add(case)
    elif report.blocks_commit:
        enrollment.status = "PROVISIONAL"

    # Persist any validation issues
    for issue in report.all_issues:
        v_issue = ValidationIssue(
            enrollment_id=enrollment.id,
            rule_code=issue.rule_code,
            severity=issue.severity,
            message=issue.explanation,
            status="OPEN",
        )
        db.add(v_issue)

    record_audit_event(
        db=db,
        actor_id=user.user_id,
        action="ENROLLMENT_RECHECK",
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        reason=f"Rechecked compliance: verdict={report.overall_verdict}, verified={report.verified}",
    )
    db.commit()

    return report.model_dump()


class UpdateEnrollmentStatusRequest(BaseModel):
    target_status: str = Field(..., description="Target lifecycle state to transition to")
    reason: Optional[str] = Field(None, description="Optional rationale for status transition")
    exceptional_reason: Optional[str] = Field(None, description="Mandatory rationale for AICTE_ADMIN reopening closed records")


@router.patch("/{enrollment_id}/status")
def update_enrollment_status(
    enrollment_id: str,
    payload: UpdateEnrollmentStatusRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    PATCH /api/enrollments/{id}/status:
    Transitions enrollment status strictly enforced through lifecycle state machine.
    Checks allowed transition table in services/lifecycle.py and caller role.
    Returns 409 Conflict with {code: "INVALID_TRANSITION", from, to, allowed: [...]} on violations.
    Releasing a seat (WITHDRAWN/CANCELLED/MIGRATED) automatically recalculates seat counts.
    Reopening closed records is restricted to AICTE_ADMIN with mandatory exceptional_reason.
    """
    from backend.services.lifecycle import transition_enrollment_status

    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment with id '{enrollment_id}' was not found.")

    scope.validate_access(enrollment.institution_id)

    transition_enrollment_status(
        db=db,
        enrollment=enrollment,
        target_status=payload.target_status,
        actor_id=user.user_id,
        actor_role=user.role,
        reason=payload.reason,
        exceptional_reason=payload.exceptional_reason,
    )
    db.commit()
    db.refresh(enrollment)

    return {
        "id": str(enrollment.id),
        "status": enrollment.status,
        "verified": enrollment.verified,
        "version": enrollment.version,
    }


