"""
Institutions & Admissions Query Router (backend/api/institutions.py).
Provides REST endpoints for querying institutions, programs, admissions,
and student credentials.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, Path, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.models.institution import Institution
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.seat import SeatAllocation
from backend.models.enrollment import Enrollment
from backend.models.student import Student
from backend.models.credential import Credential
from backend.schemas.errors import NotFoundError, BadRequestError
from backend.security.authz import (
    UserPrincipal,
    require_authenticated_user,
    institution_scope,
    InstitutionScope,
)
from backend.security.permissions import ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_AUDITOR

router = APIRouter(tags=["Institutions & Admissions"])


@router.get("/institutions")
def list_institutions(
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Returns list of institutions.
    Scoped for institution users if restricted, otherwise returns all.
    """
    query = db.query(Institution)
    if scope.is_institution_user and scope.user.institution_id:
        query = query.filter(
            or_(
                Institution.id == scope.user.institution_id,
                Institution.code == scope.user.institution_id,
            )
        )
    institutions = query.all()
    results = []
    for inst in institutions:
        progs = (
            db.query(ProgramApproval.branch)
            .filter(ProgramApproval.institution_id == inst.id)
            .distinct()
            .all()
        )
        prog_names = [p[0] for p in progs if p[0]]
        results.append({
            "id": str(inst.id),
            "code": inst.code,
            "name": inst.name,
            "status": inst.status,
            "programs": prog_names,
        })
    return results


@router.get("/institutions/{institution_id}")
def get_institution(
    institution_id: str = Path(...),
    db: Session = Depends(get_db),
):
    inst = db.query(Institution).filter(
        or_(Institution.id == institution_id, Institution.code == institution_id)
    ).first()
    if not inst:
        raise NotFoundError(f"Institution '{institution_id}' not found.")
    return {
        "id": str(inst.id),
        "code": inst.code,
        "name": inst.name,
        "status": inst.status,
    }


@router.get("/institutions/{institution_id}/programs")
def get_institution_programs(
    institution_id: str = Path(...),
    academic_year: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ProgramApproval).filter(
        or_(
            ProgramApproval.institution_id == institution_id,
            ProgramApproval.institution_id == (
                db.query(Institution.id).filter(Institution.code == institution_id).scalar_subquery()
            ),
        )
    )
    if academic_year:
        query = query.filter(ProgramApproval.academic_year == academic_year)

    approvals = query.all()
    programs = []
    for a in approvals:
        total_seats = sum(alloc.approved_count for alloc in a.seat_allocations)
        programs.append({
            "id": str(a.id),
            "program_id": str(a.id),
            "institution_id": str(a.institution_id),
            "programme": a.programme,
            "name": f"{a.programme} - {a.branch}",
            "branch": a.branch,
            "academic_year": a.academic_year,
            "total_approved_intake": total_seats,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "approval_ref": a.approval_ref,
            "version": a.version,
        })
    return programs


@router.get("/institutions/{institution_id}/snapshots/active")
def get_active_snapshot(
    institution_id: str = Path(...),
    db: Session = Depends(get_db),
):
    approval = (
        db.query(ProgramApproval)
        .filter(
            or_(
                ProgramApproval.institution_id == institution_id,
                ProgramApproval.institution_id == (
                    db.query(Institution.id).filter(Institution.code == institution_id).scalar_subquery()
                ),
            ),
            ProgramApproval.status == ApprovalStatus.FROZEN,
        )
        .order_by(ProgramApproval.version.desc())
        .first()
    )
    if not approval:
        # Fallback to any latest approval
        approval = (
            db.query(ProgramApproval)
            .filter(
                or_(
                    ProgramApproval.institution_id == institution_id,
                    ProgramApproval.institution_id == (
                        db.query(Institution.id).filter(Institution.code == institution_id).scalar_subquery()
                    ),
                )
            )
            .order_by(ProgramApproval.created_at.desc())
            .first()
        )
    if not approval:
        raise NotFoundError(f"No active approval snapshot found for '{institution_id}'.")

    allocations = {alloc.seat_type.value: alloc.approved_count for alloc in approval.seat_allocations}
    return {
        "id": str(approval.id),
        "institution_id": str(approval.institution_id),
        "academic_year": approval.academic_year,
        "approval_ref": approval.approval_ref,
        "version": approval.version,
        "status": approval.status.value,
        "frozen_at": approval.frozen_at.isoformat() if approval.frozen_at else None,
        "allocations": allocations,
    }


@router.get("/institutions/{institution_id}/seat-capacities")
def get_institution_seat_capacities(
    institution_id: str = Path(...),
    program_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(SeatAllocation).join(ProgramApproval)
    query = query.filter(
        or_(
            ProgramApproval.institution_id == institution_id,
            ProgramApproval.institution_id == (
                db.query(Institution.id).filter(Institution.code == institution_id).scalar_subquery()
            ),
        )
    )
    if program_id:
        query = query.filter(ProgramApproval.id == program_id)

    allocs = query.all()
    results = []
    for alloc in allocs:
        results.append({
            "id": str(alloc.id),
            "program_id": str(alloc.approval_id),
            "seat_type": alloc.seat_type.value if hasattr(alloc.seat_type, "value") else str(alloc.seat_type),
            "quota_type": "SUPERNUMERARY" if "SUPERNUMERARY" in str(alloc.seat_type) else "REGULAR",
            "category": alloc.seat_type.value if hasattr(alloc.seat_type, "value") else str(alloc.seat_type),
            "approved_seats": alloc.approved_count,
            "occupied_seats": 0,
            "provisional_seats": 0,
            "available_seats": alloc.approved_count,
            "status": "COMPLIANT",
        })
    return results


@router.get("/institutions/{institution_id}/admissions")
@router.get("/enrollments")
def list_institution_admissions(
    institution_id: Optional[str] = None,
    program_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Returns admission/enrollment records with full 3-layer statuses,
    student profile, credentials, and version history.
    """
    query = db.query(Enrollment).join(Student, Enrollment.student_id == Student.id)

    target_inst = institution_id
    if institution_id:
        inst_obj = db.query(Institution).filter(or_(Institution.id == institution_id, Institution.code == institution_id)).first()
        target_uuid = inst_obj.id if inst_obj else institution_id
        scope.validate_access(target_uuid)
        target_inst = target_uuid
    elif scope.is_institution_user and scope.user.institution_id:
        target_inst = scope.user.institution_id

    if target_inst:
        query = query.filter(
            or_(
                Enrollment.institution_id == target_inst,
                Enrollment.institution_id == (
                    db.query(Institution.id).filter(Institution.code == target_inst).scalar_subquery()
                ),
            )
        )

    if program_id:
        query = query.filter(Enrollment.approval_id == program_id)
    if academic_year:
        query = query.filter(Enrollment.academic_year == academic_year)
    if status:
        query = query.filter(Enrollment.status == status.upper())
    if category:
        query = query.filter(Enrollment.category == category.upper())
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Student.name.ilike(search_term),
                Student.apaar_masked.ilike(search_term),
                Enrollment.id.ilike(search_term),
            )
        )

    enrollments = query.order_by(Enrollment.admission_date.desc()).offset(offset).limit(limit).all()

    results = []
    for e in enrollments:
        student = e.student
        approval = e.approval
        cred = db.query(Credential).filter(Credential.enrollment_id == e.id).first()

        results.append({
            "id": str(e.id),
            "record_id": str(e.id),
            "enrollment_id": str(e.id),
            "student_id": str(e.student_id),
            "student_name": student.name if student else "Unknown",
            "name": student.name if student else "Unknown",
            "apaar_id": student.apaar_masked if student else "XXXX-XXXX-XXXX",
            "apaar_masked": student.apaar_masked if student else "XXXX-XXXX-XXXX",
            "dob": student.dob.strftime("%Y-%m-%d") if (student and student.dob) else "",
            "gender": student.gender if student else "O",
            "institution_id": str(e.institution_id),
            "program_id": str(e.approval_id) if e.approval_id else "",
            "programme": approval.programme if approval else "",
            "program_name": f"{approval.programme} - {approval.branch}" if approval else "",
            "branch": approval.branch if approval else "",
            "academic_year": e.academic_year,
            "seat_type": e.seat_type,
            "category": e.category,
            "quota_type": "SUPERNUMERARY" if "SUPERNUMERARY" in str(e.seat_type) else "REGULAR",
            "status": e.status,
            "verified": e.verified,
            "identity_status": getattr(e, "identity_status", "PASSED" if e.verified else "PENDING"),
            "authority_status": getattr(e, "authority_status", "PASSED" if e.verified else "PENDING"),
            "compliance_status": getattr(e, "compliance_status", "PASSED" if e.verified else "PENDING"),
            "version": getattr(e, "version", 1),
            "admission_date": e.admission_date.isoformat() if e.admission_date else "",
            "created_at": e.admission_date.isoformat() if e.admission_date else "",
            "credential": {
                "id": str(cred.id) if cred else None,
                "status": cred.status if cred else "NOT_ISSUED",
                "public_ref": cred.public_ref if cred else None,
                "qr_url": f"/api/credentials/{cred.id}/qr.png" if cred else None,
            } if cred else None,
        })

    return results


@router.get("/credentials/student/{student_id}")
def get_credential_by_student_or_enrollment(
    student_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves credential by student_id or enrollment_id.
    """
    cred = (
        db.query(Credential)
        .join(Enrollment, Credential.enrollment_id == Enrollment.id)
        .filter(
            or_(
                Enrollment.student_id == student_id,
                Credential.enrollment_id == student_id,
                Credential.id == student_id,
                Credential.public_ref == student_id,
            )
        )
        .first()
    )
    if not cred:
        raise NotFoundError("No credential found for this student.")

    return {
        "id": str(cred.id),
        "credential_id": str(cred.id),
        "enrollment_id": str(cred.enrollment_id),
        "public_ref": cred.public_ref,
        "status": cred.status,
        "payload": cred.payload,
        "signature": cred.signature,
        "key_id": cred.key_id,
        "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
        "revoked_at": cred.revoked_at.isoformat() if cred.revoked_at else None,
        "revoke_reason": cred.revoke_reason,
        "qr_url": f"/api/credentials/{cred.id}/qr.png",
        "qr_code_svg": f"/api/credentials/{cred.id}/qr.svg",
    }
