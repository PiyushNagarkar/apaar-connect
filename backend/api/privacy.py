"""
Privacy & Consent API Endpoints (backend/api/privacy.py).

Implements:
- POST /api/consent-records: Record student consent (GRANTED, PENDING, WITHDRAWN, NOT_REQUIRED).
- GET /api/consent-records: Retrieve consent history.
- POST /api/processing-basis-records: Register regulatory processing basis (separate from consent).
- GET /api/processing-basis-records: Query active processing basis records.
- POST /api/privacy/consent/toggle: Student consent toggle with statutory retention notice.
- GET /api/privacy/access-events: Sensitive data access event logs (Auditor/Admin only).
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.privacy_evidence_audit import (
    AccessEventResponse,
    ConsentRecordCreate,
    ConsentRecordResponse,
    ConsentToggleRequest,
    ProcessingBasisRecordCreate,
    ProcessingBasisRecordResponse,
)
from backend.security.authz import (
    get_current_user,
    require_authenticated_user,
    require_roles,
    UserPrincipal,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_STUDENT,
)
from backend.services.privacy_service import (
    get_access_events,
    get_consent_records,
    get_processing_basis_records,
    record_consent,
    record_processing_basis,
    toggle_student_consent,
)

router = APIRouter(tags=["Privacy & Consent"])


# ---------------------------------------------------------------------------
# 1. Student Consent Records
# ---------------------------------------------------------------------------
@router.post(
    "/consent-records",
    response_model=ConsentRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record or update student consent decision",
)
def create_consent_record_endpoint(
    req: ConsentRecordCreate,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Records student consent status: GRANTED | PENDING | WITHDRAWN | NOT_REQUIRED.
    Purposes: ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING.
    """
    rec = record_consent(
        db=db,
        student_id=req.student_id,
        purpose=req.purpose,
        consent_status=req.consent_status,
        reference=req.reference,
        actor_id=user.user_id,
    )
    db.commit()

    return ConsentRecordResponse(
        id=str(rec.id),
        student_id=str(rec.student_id),
        purpose=rec.purpose,
        consent_status=rec.consent_status,
        reference=rec.reference,
        timestamp=rec.timestamp,
        created_at=rec.created_at,
    )


@router.get(
    "/consent-records",
    response_model=List[ConsentRecordResponse],
    summary="Retrieve consent records with filters",
)
def list_consent_records_endpoint(
    student_id: Optional[str] = Query(None, description="Filter by student ID"),
    purpose: Optional[str] = Query(None, description="Filter by purpose"),
    status: Optional[str] = Query(None, description="Filter by consent status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    records = get_consent_records(
        db=db,
        student_id=student_id,
        purpose=purpose,
        consent_status=status,
        limit=limit,
        offset=offset,
    )
    return [
        ConsentRecordResponse(
            id=str(r.id),
            student_id=str(r.student_id),
            purpose=r.purpose,
            consent_status=r.consent_status,
            reference=r.reference,
            timestamp=r.timestamp,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.post(
    "/privacy/consent/toggle",
    summary="Student toggle consent for a specific purpose",
)
def toggle_consent_endpoint(
    req: ConsentToggleRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Allows a student or administrator to toggle consent.
    On WITHDRAWN: halts external sharing, while retaining legally required regulatory records.
    """
    target_student_id = user.student_id or user.user_id
    result = toggle_student_consent(
        db=db,
        student_id=target_student_id,
        purpose=req.purpose,
        consent_status=req.consent_status,
        actor_id=user.user_id,
    )
    db.commit()
    return result


# ---------------------------------------------------------------------------
# 2. Regulatory Processing Basis (Kept separate from consent)
# ---------------------------------------------------------------------------
@router.post(
    "/processing-basis-records",
    response_model=ProcessingBasisRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a statutory or regulatory processing basis",
)
def create_processing_basis_endpoint(
    req: ProcessingBasisRecordCreate,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_INSTITUTION_ADMIN)),
):
    """
    Registers legal processing basis separate from student consent.
    Establishes statutory right to retain admission records even when consent is withdrawn.
    """
    rec = record_processing_basis(
        db=db,
        basis_type=req.basis_type,
        statute_reference=req.statute_reference,
        purpose=req.purpose,
        description=req.description,
        institution_id=req.institution_id,
        student_id=req.student_id,
        valid_from=req.valid_from,
        valid_until=req.valid_until,
        actor_id=user.user_id,
    )
    db.commit()

    return ProcessingBasisRecordResponse(
        id=str(rec.id),
        institution_id=rec.institution_id,
        student_id=rec.student_id,
        basis_type=rec.basis_type,
        statute_reference=rec.statute_reference,
        purpose=rec.purpose,
        description=rec.description,
        valid_from=rec.valid_from,
        valid_until=rec.valid_until,
        is_active=rec.is_active,
        created_by=rec.created_by,
        created_at=rec.created_at,
    )


@router.get(
    "/processing-basis-records",
    response_model=List[ProcessingBasisRecordResponse],
    summary="List regulatory processing basis records",
)
def list_processing_basis_endpoint(
    institution_id: Optional[str] = Query(None),
    purpose: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    records = get_processing_basis_records(
        db=db,
        institution_id=institution_id,
        purpose=purpose,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return [
        ProcessingBasisRecordResponse(
            id=str(r.id),
            institution_id=r.institution_id,
            student_id=r.student_id,
            basis_type=r.basis_type,
            statute_reference=r.statute_reference,
            purpose=r.purpose,
            description=r.description,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
            is_active=r.is_active,
            created_by=r.created_by,
            created_at=r.created_at,
        )
        for r in records
    ]


# ---------------------------------------------------------------------------
# 3. Access Events (Sensitive Data Read Logging)
# ---------------------------------------------------------------------------
@router.get(
    "/privacy/access-events",
    response_model=List[AccessEventResponse],
    summary="Query sensitive data access logs (Auditor/Admin only)",
)
def get_access_events_endpoint(
    actor_id: Optional[str] = Query(None),
    record_type: Optional[str] = Query(None),
    record_id: Optional[str] = Query(None),
    purpose: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_AUDITOR)),
):
    """
    Returns audit log of sensitive record reads: who, what, why/purpose, when.
    Restricted to Auditor and AICTE Central Admin.
    """
    events = get_access_events(
        db=db,
        actor_id=actor_id,
        record_type=record_type,
        record_id=record_id,
        purpose=purpose,
        limit=limit,
        offset=offset,
    )
    return [
        AccessEventResponse(
            id=str(e.id),
            actor_id=e.actor_id,
            actor_role=e.actor_role,
            record_type=e.record_type,
            record_id=e.record_id,
            purpose=e.purpose,
            fields_accessed=e.fields_accessed,
            ip_address=e.ip_address,
            user_agent=e.user_agent,
            accessed_at=e.accessed_at,
        )
        for e in events
    ]
