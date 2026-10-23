"""
Identity Verification API Endpoints (L1 Verification - MOCK_APAAR_V1).
Endpoints:
- POST /api/identity/verify
- GET /api/identity/checks/{id}
- GET /api/students/{id}/identity-checks
"""
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.identity import IdentityCheck
from backend.models.student import Student
from backend.schemas.errors import NotFoundError
from backend.security.authz import (
    UserPrincipal,
    require_authenticated_user,
    institution_scope,
    InstitutionScope,
)
from backend.security.crypto import mask_apaar
from backend.services.identity_adapter import (
    get_identity_provider,
    IdentityCheckResult,
    evaluate_identity_policy,
)

identity_router = APIRouter(prefix="/identity", tags=["Identity Adapter (L1)"])
students_identity_router = APIRouter(prefix="/students", tags=["Students Identity"])


class VerifyIdentityRequest(BaseModel):
    request_id: Optional[str] = None
    apaar_id: Optional[str] = None
    student_name: str
    date_of_birth: str  # YYYY-MM-DD
    consent_reference: Optional[str] = None
    student_id: Optional[str] = None


@identity_router.post("/verify", response_model=IdentityCheckResult)
async def verify_identity(
    payload: VerifyIdentityRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    POST /api/identity/verify:
    Executes student identity verification against the configured identity provider (MOCK_APAAR_V1).
    Stores every check in the identity_checks database table.
    Never logs full APAAR IDs (always masked).
    """
    resolved_req_id = payload.request_id or getattr(request.state, "request_id", None) or f"req-{uuid.uuid4().hex[:12]}"
    provider = get_identity_provider()

    # Never log full APAAR IDs
    masked_apaar = mask_apaar(payload.apaar_id)

    # Perform deterministic verification
    result = await provider.verify(
        request_id=resolved_req_id,
        apaar_id=payload.apaar_id,
        student_name=payload.student_name,
        date_of_birth=payload.date_of_birth,
        consent_reference=payload.consent_reference,
    )

    # Store check in identity_checks table
    db_check = IdentityCheck(
        id=result.check_id,
        student_id=payload.student_id,
        request_id=resolved_req_id,
        source=result.source,
        status=result.status,
        exists=result.exists,
        name_match=result.name_match,
        dob_match=result.dob_match,
        raw={
            "apaar_masked": masked_apaar,
            "reason_code": result.reason_code,
            "consent_reference": payload.consent_reference,
            "details": result.raw_details,
        },
    )
    db.add(db_check)
    db.commit()

    return result


@identity_router.get("/checks/{check_id}")
def get_identity_check(
    check_id: str,
    db: Session = Depends(get_db),
):
    """
    GET /api/identity/checks/{id}:
    Retrieves stored identity check result by its unique check ID.
    """
    check = db.query(IdentityCheck).filter(IdentityCheck.id == check_id).first()
    if not check:
        raise NotFoundError(f"Identity check '{check_id}' was not found.")

    return {
        "check_id": str(check.id),
        "student_id": str(check.student_id) if check.student_id else None,
        "request_id": check.request_id,
        "source": check.source,
        "status": check.status,
        "exists": check.exists,
        "name_match": check.name_match,
        "dob_match": check.dob_match,
        "created_at": check.created_at.isoformat(),
        "raw": check.raw,
    }


@students_identity_router.get("/{student_id}/identity-checks")
def get_student_identity_checks(
    student_id: str,
    current_user: UserPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/students/{id}/identity-checks:
    Retrieves all identity checks performed for the specified student.
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise NotFoundError(f"Student '{student_id}' was not found.")

    checks = (
        db.query(IdentityCheck)
        .filter(IdentityCheck.student_id == student_id)
        .order_by(IdentityCheck.created_at.desc())
        .all()
    )

    return {
        "student_id": student_id,
        "total_checks": len(checks),
        "checks": [
            {
                "check_id": str(c.id),
                "request_id": c.request_id,
                "source": c.source,
                "status": c.status,
                "exists": c.exists,
                "name_match": c.name_match,
                "dob_match": c.dob_match,
                "created_at": c.created_at.isoformat(),
                "raw": c.raw,
            }
            for c in checks
        ],
    }
