"""
Review Cases API (backend/api/review_cases.py)

Endpoints:
- GET /api/review-cases: Scoped list of review cases with SLA/overdue metrics.
- POST /api/review-cases: Creates a review case.
- GET /api/review-cases/{id}: Case details with evidence and SLA.
- POST /api/review-cases/{id}/assign: Assigns case to an AICTE reviewer.
- POST /api/review-cases/{id}/evidence: Attaches evidence reference + SHA-256 hash.
- PATCH /api/review-cases/{id}: Decides case (consequence applied to enrollment via state machine).
- GET /api/review-cases/{id}/history: Chronological audit history.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.student import Student
from backend.models.user import User
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.security.authz import (
    InstitutionScope,
    UserPrincipal,
    institution_scope,
    require_authenticated_user,
)
from backend.services.review_service import (
    assign_review_case,
    attach_evidence_reference,
    calculate_hours_remaining,
    create_review_case,
    decide_review_case,
    get_review_case_history,
    is_case_overdue,
)

router = APIRouter(prefix="/review-cases", tags=["Review Cases"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateReviewCaseRequest(BaseModel):
    type: str = Field(..., description="DUPLICATE, IDENTITY_MISMATCH, SEAT_EXCEPTION, APPROVAL_MISMATCH, etc.")
    enrollment_id: str
    severity: str = Field("MEDIUM", description="CRITICAL, HIGH, MEDIUM, LOW")
    priority: Optional[float] = None
    evidence: Optional[Dict[str, Any]] = None
    assigned_to: Optional[str] = None


class AssignReviewCaseRequest(BaseModel):
    assignee_id: str = Field(..., description="User ID of the assigned AICTE reviewer")


class AttachEvidenceRequest(BaseModel):
    evidence_ref: str = Field(..., description="Formal institutional document reference")
    evidence_hash: str = Field(..., description="SHA-256 hexadecimal digest of document")
    description: Optional[str] = None


class DecideReviewCaseRequest(BaseModel):
    decision: str = Field(..., description="DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT, WITHDRAW_ONE_RECORD, CONFIRM, REJECT, ESCALATE")
    decision_reason: str = Field(..., min_length=3, description="Mandatory reason for decision")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
def list_review_cases(
    type: Optional[str] = Query(None, description="Filter by case type"),
    status: Optional[str] = Query(None, description="Filter by status (OPEN, ASSIGNED, AWAITING_INSTITUTION, UNDER_DECISION, RESOLVED, ESCALATED)"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    is_overdue: Optional[bool] = Query(None, description="Filter overdue cases (past SLA due_at)"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned reviewer ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Returns scoped list of review cases.
    Institution users only see cases for their own institution.
    Exposes is_overdue and hours_remaining for dashboard monitoring.
    """
    query = db.query(ReviewCase)

    if scope.is_institution_user:
        user_inst = scope.user.institution_id
        query = query.join(Enrollment, ReviewCase.enrollment_id == Enrollment.id).filter(
            Enrollment.institution_id == user_inst
        )

    if type:
        query = query.filter(ReviewCase.type == type.upper())
    if status:
        query = query.filter(ReviewCase.status == status.upper())
    if severity:
        query = query.filter(ReviewCase.severity == severity.upper())
    if assigned_to:
        query = query.filter(ReviewCase.assigned_to == assigned_to)

    cases = query.order_by(ReviewCase.priority.desc(), ReviewCase.created_at.desc()).all()

    # Filter by is_overdue if requested
    if is_overdue is not None:
        cases = [c for c in cases if is_case_overdue(c) == is_overdue]

    total = len(cases)
    paged = cases[offset : offset + limit]

    items = []
    for c in paged:
        enroll = c.enrollment
        student = enroll.student if enroll else None
        inst = enroll.institution if enroll else None
        assignee = c.assignee

        evidence_items = (c.evidence or {}).get("items", [])

        items.append({
            "id": str(c.id),
            "type": c.type,
            "severity": c.severity,
            "priority": c.priority,
            "status": c.status,
            "decision": c.decision,
            "decision_reason": c.decision_reason,
            "enrollment_id": str(c.enrollment_id),
            "institution_id": str(enroll.institution_id) if enroll else None,
            "institution_name": inst.name if inst else None,
            "student_name": student.name if student else None,
            "assigned_to": str(c.assigned_to) if c.assigned_to else None,
            "assignee_name": assignee.email if assignee else None,
            "due_at": c.due_at.isoformat() if c.due_at else None,
            "is_overdue": is_case_overdue(c),
            "hours_remaining": calculate_hours_remaining(c),
            "evidence_count": len(evidence_items),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=201)
def create_case(
    req: CreateReviewCaseRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Opens a new review case."""
    enroll = db.query(Enrollment).filter(Enrollment.id == req.enrollment_id).first()
    if not enroll:
        raise NotFoundError(f"Enrollment '{req.enrollment_id}' not found.")
    scope.validate_access(enroll.institution_id)

    case = create_review_case(
        db=db,
        type_str=req.type,
        enrollment_id=req.enrollment_id,
        severity=req.severity,
        priority=req.priority,
        evidence=req.evidence,
        assigned_to=req.assigned_to,
        actor_id=user.user_id,
    )
    db.commit()
    return {"id": str(case.id), "status": case.status, "due_at": case.due_at.isoformat()}


@router.get("/{case_id}")
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Retrieves full details of a single review case."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    enroll = case.enrollment
    if enroll:
        scope.validate_access(enroll.institution_id)

    student = enroll.student if enroll else None
    inst = enroll.institution if enroll else None
    assignee = case.assignee

    return {
        "id": str(case.id),
        "type": case.type,
        "severity": case.severity,
        "priority": case.priority,
        "status": case.status,
        "decision": case.decision,
        "decision_reason": case.decision_reason,
        "enrollment_id": str(case.enrollment_id),
        "institution_id": str(enroll.institution_id) if enroll else None,
        "institution_name": inst.name if inst else None,
        "student_name": student.name if student else None,
        "apaar_masked": student.apaar_masked if student else None,
        "assigned_to": str(case.assigned_to) if case.assigned_to else None,
        "assignee_name": assignee.email if assignee else None,
        "evidence": case.evidence,
        "due_at": case.due_at.isoformat() if case.due_at else None,
        "is_overdue": is_case_overdue(case),
        "hours_remaining": calculate_hours_remaining(case),
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


@router.post("/{case_id}/assign")
def assign_case(
    case_id: str,
    req: AssignReviewCaseRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """Assigns case to an AICTE reviewer."""
    case = assign_review_case(
        db=db,
        case_id=case_id,
        assignee_id=req.assignee_id,
        actor_id=user.user_id,
        actor_role=user.role,
    )
    db.commit()
    return {"id": str(case.id), "assigned_to": case.assigned_to, "status": case.status}


@router.post("/{case_id}/evidence")
def submit_evidence(
    case_id: str,
    req: AttachEvidenceRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Attaches institutional evidence reference + SHA-256 hash (never raw documents).
    If case was awaiting institution, automatically advances to UNDER_DECISION.
    """
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    enroll = case.enrollment
    if enroll:
        scope.validate_access(enroll.institution_id)

    case = attach_evidence_reference(
        db=db,
        case_id=case_id,
        evidence_ref=req.evidence_ref,
        evidence_hash=req.evidence_hash,
        description=req.description,
        actor_id=user.user_id,
        actor_role=user.role,
    )
    db.commit()
    return {"id": str(case.id), "status": case.status, "evidence_attached": True}


@router.patch("/{case_id}")
def decide_case(
    case_id: str,
    req: DecideReviewCaseRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Decides a review case:
    Decisions: DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT, WITHDRAW_ONE_RECORD,
               CONFIRM, REJECT, ESCALATE.
    Applies consequences to enrollment strictly via lifecycle state machine.
    Institutions cannot approve or decide review cases (raises 403 Forbidden).
    """
    case = decide_review_case(
        db=db,
        case_id=case_id,
        decision=req.decision,
        decision_reason=req.decision_reason,
        actor_id=user.user_id,
        actor_role=user.role,
    )
    db.commit()
    return {
        "id": str(case.id),
        "status": case.status,
        "decision": case.decision,
        "decision_reason": case.decision_reason,
        "enrollment_status": case.enrollment.status if case.enrollment else None,
    }


@router.get("/{case_id}/history")
def get_history(
    case_id: str,
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """Returns complete chronological audit history for a review case."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")
    if case.enrollment:
        scope.validate_access(case.enrollment.institution_id)

    events = get_review_case_history(db=db, case_id=case_id)
    return {"case_id": case_id, "history": events}
