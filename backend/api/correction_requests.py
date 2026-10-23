"""
Correction Requests API (backend/api/correction_requests.py)

Endpoints:
- POST /api/correction-requests: Requests official correction for an enrollment record.
- GET /api/correction-requests: Scoped list of correction requests.
- GET /api/correction-requests/{id}: Details of single correction request.
- PATCH /api/correction-requests/{id}: Approves/rejects correction request.
  Upon approval, increments enrollment version to N+1, writes RecordVersion before/after snapshot,
  and retains old version permanently.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.correction import CorrectionRequest
from backend.models.enrollment import Enrollment
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.security.authz import (
    InstitutionScope,
    UserPrincipal,
    institution_scope,
    require_authenticated_user,
)
from backend.services.review_service import (
    create_correction_request,
    decide_correction_request,
)

router = APIRouter(prefix="/correction-requests", tags=["Correction Requests"])


class CreateCorrectionRequestSchema(BaseModel):
    enrollment_id: str
    reason_code: str = Field(..., description="DATA_ENTRY_ERROR, OFFICIAL_CORRECTION, NAME_CORRECTION, DOB_CORRECTION, etc.")
    explanation: str = Field(..., min_length=3)
    proposed_changes: Dict[str, Any] = Field(..., description="Proposed field modifications, e.g. {'name': 'New Name'}")


class DecideCorrectionRequestSchema(BaseModel):
    approve: bool = Field(..., description="True to approve and create Version N+1, False to reject")
    decision_reason: str = Field(..., min_length=3)


@router.post("", status_code=201)
def submit_correction_request(
    payload: CreateCorrectionRequestSchema,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Submits a correction request capturing current record snapshot."""
    enroll = db.query(Enrollment).filter(Enrollment.id == payload.enrollment_id).first()
    if not enroll:
        raise NotFoundError(f"Enrollment '{payload.enrollment_id}' not found.")
    scope.validate_access(enroll.institution_id)

    req = create_correction_request(
        db=db,
        enrollment_id=payload.enrollment_id,
        reason_code=payload.reason_code,
        explanation=payload.explanation,
        proposed_changes=payload.proposed_changes,
        actor_id=user.user_id,
        institution_id=enroll.institution_id,
    )
    db.commit()
    return {"id": str(req.id), "status": req.status, "reason_code": req.reason_code}


@router.get("")
def list_correction_requests(
    enrollment_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="PENDING, APPROVED, REJECTED"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Returns scoped list of correction requests."""
    query = db.query(CorrectionRequest)

    if scope.is_institution_user:
        query = query.filter(CorrectionRequest.institution_id == scope.user.institution_id)

    if enrollment_id:
        query = query.filter(CorrectionRequest.enrollment_id == enrollment_id)
    if status:
        query = query.filter(CorrectionRequest.status == status.upper())

    total = query.count()
    items = query.order_by(CorrectionRequest.created_at.desc()).offset(offset).limit(limit).all()

    out = []
    for r in items:
        out.append({
            "id": str(r.id),
            "enrollment_id": str(r.enrollment_id),
            "institution_id": str(r.institution_id),
            "status": r.status,
            "reason_code": r.reason_code,
            "explanation": r.explanation,
            "proposed_changes": r.proposed_changes,
            "version_created": r.version_created,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"items": out, "total": total, "limit": limit, "offset": offset}


@router.get("/{request_id}")
def get_correction_request(
    request_id: str,
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Retrieves full details of a single correction request with before/after state."""
    r = db.query(CorrectionRequest).filter(CorrectionRequest.id == request_id).first()
    if not r:
        raise NotFoundError(f"Correction request '{request_id}' not found.")
    scope.validate_access(r.institution_id)

    return {
        "id": str(r.id),
        "enrollment_id": str(r.enrollment_id),
        "institution_id": str(r.institution_id),
        "status": r.status,
        "reason_code": r.reason_code,
        "explanation": r.explanation,
        "proposed_changes": r.proposed_changes,
        "previous_state": r.previous_state,
        "approved_by": str(r.approved_by) if r.approved_by else None,
        "decision_reason": r.decision_reason,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "version_created": r.version_created,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.patch("/{request_id}")
def decide_request(
    request_id: str,
    payload: DecideCorrectionRequestSchema,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Decides a correction request (Approve / Reject).
    If approved, creates Version N+1 with before/after snapshot.
    Institutions cannot approve correction requests (raises 403 Forbidden).
    """
    req = decide_correction_request(
        db=db,
        request_id=request_id,
        approve=payload.approve,
        decision_reason=payload.decision_reason,
        actor_id=user.user_id,
        actor_role=user.role,
    )
    db.commit()
    return {
        "id": str(req.id),
        "status": req.status,
        "version_created": req.version_created,
        "decision_reason": req.decision_reason,
    }
