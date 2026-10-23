"""
Duplicate Detection API (backend/api/duplicates.py)

Exposes:
- POST /api/duplicates/check: Candidate generator and scorer endpoint.
- GET /api/duplicates/candidates: Scoped list of detected duplicate candidates.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.student import Student
from backend.schemas.errors import BadRequestError, NotFoundError
from backend.security.authz import (
    InstitutionScope,
    UserPrincipal,
    institution_scope,
    require_authenticated_user,
)
from backend.services.duplicate_detection import (
    DuplicateDetectionService,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_MEDIUM,
    TIER_FUZZY,
    TIER_PROGRESSION,
)

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------
class DuplicateCheckRequest(BaseModel):
    enrollment_id: Optional[str] = Field(None, description="Existing enrollment UUID to evaluate")
    apaar_id: Optional[str] = Field(None, description="12-digit APAAR identifier")
    apaar_hash: Optional[str] = Field(None, description="Keyed blind index hash of APAAR")
    name: Optional[str] = Field(None, description="Student full name")
    dob: Optional[str] = Field(None, description="Date of birth (ISO YYYY-MM-DD or standard formats)")
    mobile: Optional[str] = Field(None, description="10-digit mobile number")
    email: Optional[str] = Field(None, description="Student email address")
    institution_id: Optional[str] = Field(None, description="Target institution UUID")
    academic_year: Optional[str] = Field(None, description="Academic year (e.g. 2024-25)")
    save_candidates: bool = Field(False, description="Whether to persist detected candidate matches to database")


class MatchItemResponse(BaseModel):
    match_type: str
    score: float
    reasons: List[str]
    enrollment_a: Optional[str] = None
    enrollment_b: Optional[str] = None
    student_a: Optional[str] = None
    student_b: Optional[str] = None
    requires_case: bool
    is_progression: bool
    details: Dict[str, Any] = {}


class DuplicateCheckResponse(BaseModel):
    total_matches: int
    highest_tier: Optional[str] = None
    has_critical: bool
    has_high: bool
    matches: List[MatchItemResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/check", response_model=DuplicateCheckResponse)
def check_duplicates(
    req: DuplicateCheckRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Evaluates an admission record against the active database for duplicate candidates.
    Supports candidate blocking on DOB, mobile_last10, and apaar_hash.
    Returns matched tiers, component scores, and reason codes.
    """
    service = DuplicateDetectionService(db=db)

    # Scoping check
    target_inst_id = req.institution_id
    if scope.is_institution_user:
        target_inst_id = scope.user.institution_id

    matches = []
    if req.enrollment_id:
        enroll = db.query(Enrollment).filter(Enrollment.id == req.enrollment_id).first()
        if not enroll:
            raise NotFoundError(f"Enrollment '{req.enrollment_id}' not found.")
        scope.validate_access(enroll.institution_id)

        matches = service.check_enrollment(
            enrollment_id=req.enrollment_id,
            save_candidates=req.save_candidates,
            actor_id=user.user_id,
        )
    else:
        # Ad-hoc record check
        record = {
            "apaar_id": req.apaar_id,
            "apaar_hash": req.apaar_hash,
            "name": req.name,
            "dob": req.dob,
            "mobile": req.mobile,
            "email": req.email,
            "institution_id": target_inst_id,
            "academic_year": req.academic_year,
            "status": "ACTIVE",
        }
        matches = service.check_record(
            record=record,
            save_candidates=req.save_candidates,
            actor_id=user.user_id,
        )

    # Determine highest tier
    tier_order = [TIER_CRITICAL, TIER_HIGH, TIER_MEDIUM, TIER_FUZZY, TIER_PROGRESSION]
    highest_tier = None
    for t in tier_order:
        if any(m.match_type == t for m in matches):
            highest_tier = t
            break

    if req.save_candidates:
        db.commit()

    return DuplicateCheckResponse(
        total_matches=len(matches),
        highest_tier=highest_tier,
        has_critical=any(m.match_type == TIER_CRITICAL for m in matches),
        has_high=any(m.match_type == TIER_HIGH for m in matches),
        matches=[
            MatchItemResponse(
                match_type=m.match_type,
                score=m.score,
                reasons=m.reasons,
                enrollment_a=m.enrollment_a_id,
                enrollment_b=m.enrollment_b_id,
                student_a=m.student_a_id,
                student_b=m.student_b_id,
                requires_case=m.requires_case,
                is_progression=m.is_progression,
                details=m.details,
            )
            for m in matches
        ],
    )


@router.get("/candidates")
def list_duplicate_candidates(
    status: Optional[str] = Query(None, description="Filter by status (DETECTED, UNDER_REVIEW, RESOLVED, DISMISSED, LOGGED_PROGRESSION)"),
    match_type: Optional[str] = Query(None, description="Filter by tier (CRITICAL, HIGH, MEDIUM, FUZZY, PROGRESSION)"),
    institution_id: Optional[str] = Query(None, description="Filter by institution UUID"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum similarity score filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    scope: InstitutionScope = Depends(institution_scope),
):
    """
    Returns detected duplicate candidate pairs with enrollment and student metadata.
    Enforces institutional scoping for institution users.
    """
    query = db.query(DuplicateCandidate)

    if status:
        query = query.filter(DuplicateCandidate.status == status)

    if match_type:
        query = query.filter(DuplicateCandidate.match_type == match_type)

    if min_score is not None:
        query = query.filter(DuplicateCandidate.score >= min_score)

    # Scoping
    if scope.is_institution_user:
        user_inst = scope.user.institution_id
        query = query.join(
            Enrollment,
            or_(
                DuplicateCandidate.enrollment_a == Enrollment.id,
                DuplicateCandidate.enrollment_b == Enrollment.id,
            ),
        ).filter(Enrollment.institution_id == user_inst)
    elif institution_id:
        query = query.join(
            Enrollment,
            or_(
                DuplicateCandidate.enrollment_a == Enrollment.id,
                DuplicateCandidate.enrollment_b == Enrollment.id,
            ),
        ).filter(Enrollment.institution_id == institution_id)

    total = query.count()
    items = query.order_by(DuplicateCandidate.created_at.desc()).offset(offset).limit(limit).all()

    candidates_out = []
    for c in items:
        ea: Optional[Enrollment] = c.enrollment_first
        eb: Optional[Enrollment] = c.enrollment_second

        def _enroll_info(e: Optional[Enrollment]) -> Optional[Dict[str, Any]]:
            if not e:
                return None
            s = e.student
            inst = e.institution
            return {
                "enrollment_id": str(e.id),
                "institution_id": str(e.institution_id),
                "institution_name": inst.name if inst else None,
                "institution_code": inst.code if inst else None,
                "academic_year": e.academic_year,
                "seat_type": e.seat_type,
                "status": e.status,
                "student_name": s.name if s else None,
                "student_dob": s.dob.strftime("%Y-%m-%d") if (s and s.dob) else None,
                "apaar_masked": s.apaar_masked if s else None,
            }

        candidates_out.append({
            "id": str(c.id),
            "match_type": c.match_type,
            "score": c.score,
            "reasons": c.reasons,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "enrollment_a": _enroll_info(ea),
            "enrollment_b": _enroll_info(eb),
        })

    return {
        "items": candidates_out,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
