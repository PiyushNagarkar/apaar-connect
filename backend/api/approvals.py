"""
Approval Management & Seat Matrix Endpoints:
- POST /api/admin/approvals (AICTE_ADMIN only)
- POST /api/admin/approvals/import (CSV with preview + row validation errors; AICTE_ADMIN only)
- POST /api/admin/approvals/{id}/freeze (AICTE_ADMIN only)
- POST /api/admin/approvals/{id}/supersede (AICTE_ADMIN only)
- GET /api/admin/approvals/{id}/history
- GET /api/admin/rule-versions & POST /api/admin/rule-versions
- GET /api/approvals (Scoped: institution users read only their own approvals)
- GET /api/seat-matrix (Real-time seat matrix with zero-approved category handling)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.rule_config import RuleVersionConfig
from backend.schemas.approval import (
    CreateApprovalRequest,
    SupersedeApprovalRequest,
    CsvImportRequest,
    RuleVersionCreateRequest,
)
from backend.schemas.errors import NotFoundError, AppException
from backend.security.authz import (
    UserPrincipal,
    require_authenticated_user,
    require_roles,
    institution_scope,
    InstitutionScope,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
)
from backend.services.approval_service import (
    create_approval,
    update_draft_approval,
    freeze_approval,
    supersede_approval,
    get_approval_history,
    import_approvals_csv,
    calculate_seat_matrix,
    HANDBOOK_NOTE,
    DEFAULT_RULE_VERSION,
)

admin_router = APIRouter(prefix="/admin", tags=["Admin Approval Management"])
general_router = APIRouter(tags=["Approvals & Seat Matrix"])


# ---------------------------------------------------------------------------
# Admin Endpoints (Writes strictly restricted to AICTE_ADMIN)
# ---------------------------------------------------------------------------

@admin_router.post("/approvals", status_code=status.HTTP_201_CREATED)
def api_create_approval(
    payload: CreateApprovalRequest,
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
    db: Session = Depends(get_db),
):
    """
    POST /api/admin/approvals:
    Creates a new DRAFT approval with one seat_allocations row per seat_type.
    Only AICTE_ADMIN can execute write operations.
    """
    approval = create_approval(
        db=db,
        institution_id=payload.institution_id,
        programme=payload.programme,
        branch=payload.branch,
        academic_year=payload.academic_year,
        approval_ref=payload.approval_ref,
        campus=payload.campus,
        shift=payload.shift,
        allocations=payload.allocations,
        rule_version=payload.rule_version,
        actor_id=user.user_id,
    )
    allocs = {a.seat_type.value: a.approved_count for a in approval.seat_allocations}
    return {
        "id": str(approval.id),
        "status": approval.status.value,
        "approval_ref": approval.approval_ref,
        "academic_year": approval.academic_year,
        "programme": approval.programme,
        "branch": approval.branch,
        "version": approval.version,
        "allocations": allocs,
    }


@admin_router.post("/approvals/import")
def api_import_approvals(
    payload: CsvImportRequest,
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
    db: Session = Depends(get_db),
):
    """
    POST /api/admin/approvals/import:
    Parses and validates CSV approvals import with preview and row errors.
    If commit=False (default), runs in preview mode without writing to DB.
    """
    result = import_approvals_csv(
        db=db,
        csv_text=payload.csv_content,
        commit=payload.commit,
        actor_id=user.user_id,
    )
    return result


@admin_router.post("/approvals/{approval_id}/freeze")
def api_freeze_approval(
    approval_id: str,
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
    db: Session = Depends(get_db),
):
    """
    POST /api/admin/approvals/{id}/freeze:
    Freezes approval, making it and allocations immutable.
    Records snapshot in record_versions.
    """
    frozen = freeze_approval(
        db=db,
        approval_id=approval_id,
        actor_email=user.email or "admin@aicte.gov.in",
        actor_id=user.user_id,
    )
    return {
        "id": str(frozen.id),
        "status": frozen.status.value,
        "approval_ref": frozen.approval_ref,
        "version": frozen.version,
        "frozen_at": frozen.frozen_at.isoformat() if frozen.frozen_at else None,
        "frozen_by": frozen.frozen_by,
    }


@admin_router.post("/approvals/{approval_id}/supersede")
def api_supersede_approval(
    approval_id: str,
    payload: SupersedeApprovalRequest,
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
    db: Session = Depends(get_db),
):
    """
    POST /api/admin/approvals/{id}/supersede:
    Creates version N+1 with supersedes_id and mandatory change reason.
    Old version remains unchanged and readable.
    """
    updates = {}
    for f in ["programme", "branch", "campus", "shift", "academic_year", "approval_ref"]:
        val = getattr(payload, f)
        if val is not None:
            updates[f] = val

    new_approval = supersede_approval(
        db=db,
        approval_id=approval_id,
        change_reason=payload.change_reason,
        updates=updates,
        allocations=payload.allocations,
        actor_email=user.email or "admin@aicte.gov.in",
        actor_id=user.user_id,
    )
    allocs = {a.seat_type.value: a.approved_count for a in new_approval.seat_allocations}
    return {
        "id": str(new_approval.id),
        "version": new_approval.version,
        "supersedes_id": str(new_approval.supersedes_id),
        "status": new_approval.status.value,
        "approval_ref": new_approval.approval_ref,
        "allocations": allocs,
    }


@admin_router.get("/approvals/{approval_id}/history")
def api_get_approval_history(
    approval_id: str,
    user: UserPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/admin/approvals/{id}/history:
    Returns the version lineage (v1, v2, ...) and field/seat diffs.
    """
    return get_approval_history(db, approval_id)


@admin_router.get("/rule-versions")
def api_get_rule_versions(
    user: UserPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/admin/rule-versions:
    Returns configured handbook rule versions with visible handbook note.
    """
    configs = db.query(RuleVersionConfig).filter(RuleVersionConfig.is_active == True).all()
    if not configs:
        # Default fallback
        return {
            "handbook_note": HANDBOOK_NOTE,
            "rule_versions": [
                {
                    "rule_version": DEFAULT_RULE_VERSION,
                    "academic_year": "2024-2025",
                    "handbook_note": HANDBOOK_NOTE,
                    "allowed_seat_types": [
                        "REGULAR",
                        "NRI",
                        "SUPERNUMERARY_FN_OCI_PIO",
                        "SUPERNUMERARY_GULF_WORKER_CHILD",
                        "OTHER",
                    ],
                }
            ],
        }
    return {
        "handbook_note": HANDBOOK_NOTE,
        "rule_versions": [
            {
                "id": str(c.id),
                "rule_version": c.rule_version,
                "academic_year": c.academic_year,
                "description": c.description,
                "allowed_seat_types": c.allowed_seat_types,
                "handbook_note": c.handbook_note,
            }
            for c in configs
        ],
    }


@admin_router.post("/rule-versions", status_code=status.HTTP_201_CREATED)
def api_create_rule_version(
    payload: RuleVersionCreateRequest,
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
    db: Session = Depends(get_db),
):
    """
    POST /api/admin/rule-versions:
    Configures new rule version (AICTE_ADMIN only).
    """
    existing = db.query(RuleVersionConfig).filter(RuleVersionConfig.rule_version == payload.rule_version).first()
    if existing:
        existing.academic_year = payload.academic_year
        existing.description = payload.description
        existing.allowed_seat_types = payload.allowed_seat_types
        existing.handbook_note = HANDBOOK_NOTE
        db.commit()
        db.refresh(existing)
        return {"id": str(existing.id), "rule_version": existing.rule_version, "handbook_note": HANDBOOK_NOTE}

    config = RuleVersionConfig(
        rule_version=payload.rule_version,
        academic_year=payload.academic_year,
        description=payload.description,
        allowed_seat_types=payload.allowed_seat_types,
        handbook_note=HANDBOOK_NOTE,
        is_active=True,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return {"id": str(config.id), "rule_version": config.rule_version, "handbook_note": HANDBOOK_NOTE}


# ---------------------------------------------------------------------------
# General Scoped Endpoints (Institutions get read-only access to their own data)
# ---------------------------------------------------------------------------

@general_router.get("/approvals")
def api_get_approvals(
    academic_year: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/approvals:
    Scoped retrieval:
    - Institution users automatically restricted to their own institution_id.
    - AICTE_ADMIN, AICTE_REVIEWER, AUDITOR can view all institutions.
    """
    query = db.query(ProgramApproval)

    # Apply institution isolation filter
    query = scope.filter_query(query, ProgramApproval)

    if academic_year:
        query = query.filter(ProgramApproval.academic_year == academic_year)
    if status_filter:
        query = query.filter(ProgramApproval.status == status_filter.upper())

    approvals = query.order_by(ProgramApproval.created_at.desc()).all()
    results = []
    for a in approvals:
        allocs = {alloc.seat_type.value: alloc.approved_count for alloc in a.seat_allocations}
        results.append({
            "id": str(a.id),
            "institution_id": str(a.institution_id),
            "programme": a.programme,
            "branch": a.branch,
            "campus": a.campus,
            "shift": a.shift,
            "academic_year": a.academic_year,
            "approval_ref": a.approval_ref,
            "version": a.version,
            "status": a.status.value,
            "frozen_at": a.frozen_at.isoformat() if a.frozen_at else None,
            "frozen_by": a.frozen_by,
            "supersedes_id": str(a.supersedes_id) if a.supersedes_id else None,
            "seat_allocations": allocs,
        })
    return {"total": len(results), "approvals": results}


@general_router.get("/seat-matrix")
def api_get_seat_matrix(
    institution_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    approval_id: Optional[str] = Query(None),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/seat-matrix:
    Returns per seat_type:
    - approved
    - confirmed+active occupied
    - provisional (shown separately)
    - available
    - utilisation %
    Explicitly handles approved=0 (any admissions flagged 'no approval for this category').
    Scoped to caller's institution for institution users.
    """
    # Enforce institution scope: institution users can only inspect own institution
    target_institution_id = scope.validate_access(institution_id)

    matrix_data = calculate_seat_matrix(
        db=db,
        institution_id=target_institution_id or None,
        academic_year=academic_year,
        approval_id=approval_id,
    )
    return matrix_data
