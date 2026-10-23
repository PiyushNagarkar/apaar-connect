"""
Audit & Retention Policy API Endpoints (backend/api/audit.py).

Implements:
- GET /api/audit-events: Filtered audit log query (actor, institution, entity, action, time).
- POST /api/audit-events/verify-chain: Cryptographic hash chain verification report.
- GET /api/retention-policies: Configurable retention table for admin UI.
- PUT /api/retention-policies/{category}: Update retention policy duration and rules.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.schemas.privacy_evidence_audit import (
    AuditChainVerifyResponse,
    AuditEventResponse,
    RetentionPolicyResponse,
    RetentionPolicyUpdateRequest,
)
from backend.security.authz import (
    require_authenticated_user,
    require_roles,
    UserPrincipal,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
)
from backend.services.audit_service import (
    get_audit_events,
    get_retention_policies,
    update_retention_policy,
    verify_audit_hash_chain,
)
from backend.services.privacy_service import log_access_event

router = APIRouter(tags=["Audit & Compliance"])


# ---------------------------------------------------------------------------
# 1. Audit Events (Append-Only Event Querying)
# ---------------------------------------------------------------------------
@router.get(
    "/audit-events",
    response_model=List[AuditEventResponse],
    summary="Query append-only audit events with filters (Auditor/Admin only)",
)
def list_audit_events_endpoint(
    request: Request,
    actor_id: Optional[str] = Query(None, description="Filter by actor ID"),
    institution_id: Optional[str] = Query(None, description="Filter by institution ID"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (ENROLLMENT, STUDENT, CREDENTIAL, etc.)"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    action: Optional[str] = Query(None, description="Filter by action verb (e.g. CREATE, UPDATE, REVOKE)"),
    start_time: Optional[datetime] = Query(None, description="Filter events after timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter events before timestamp"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_AUDITOR)),
):
    """
    Returns audit events recorded across all write state changes.
    Equipped with prev_hash and hash for cryptographic chaining verification.
    """
    events = get_audit_events(
        db=db,
        actor_id=actor_id,
        institution_id=institution_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_access_event(
        db=db,
        actor_id=user.user_id,
        actor_role=user.role,
        record_type="AUDIT_LOGS",
        record_id="QUERY",
        purpose="AUDITOR_INSPECTION",
        fields_accessed=["actor_id", "action", "entity_type", "hash", "prev_hash"],
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.commit()

    return [
        AuditEventResponse(
            id=str(e.id),
            actor_id=e.actor_id,
            institution_id=e.institution_id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=str(e.entity_id),
            reason=e.reason,
            request_id=e.request_id,
            prev_hash=e.prev_hash,
            hash=e.hash,
            created_at=e.created_at,
        )
        for e in events
    ]


@router.post(
    "/audit-events/verify-chain",
    response_model=AuditChainVerifyResponse,
    summary="Cryptographically verify audit event hash chain from genesis to tail",
)
def verify_audit_chain_endpoint(
    limit: Optional[int] = Query(None, ge=1, le=100000, description="Max events to verify or null for all"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AUDITOR)),
):
    """
    Verifies that every audit event's hash satisfies:
    hash = SHA256(prev_hash + canonical_event)
    and that row[i].prev_hash matches row[i-1].hash.
    Detects any inserted, modified, or deleted events in the chain.
    """
    res = verify_audit_hash_chain(db=db, limit=limit)
    return AuditChainVerifyResponse(
        chain_valid=res["chain_valid"],
        total_events_checked=res["total_events_checked"],
        genesis_hash=res["genesis_hash"],
        tail_hash=res["tail_hash"],
        broken_links=res["broken_links"],
    )


# ---------------------------------------------------------------------------
# 2. Configurable Retention Policies (Admin UI)
# ---------------------------------------------------------------------------
@router.get(
    "/retention-policies",
    response_model=List[RetentionPolicyResponse],
    summary="List configurable retention policies for rejected, withdrawn, and duplicate records",
)
def list_retention_policies_endpoint(
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Displays the retention policy configuration table in the Admin UI:
    - REJECTED: Retention mandate for rejected admissions / non-approved filings.
    - WITHDRAWN: Statutory retention post-withdrawal for fee reconciliation & seat accounting.
    - DUPLICATE: Retention for resolved duplicate candidates & synthetic conflict logs.
    - UNRESOLVED_EXCEPTIONS: Statutory retention for disputed enrollments and overages.
    """
    policies = get_retention_policies(db)
    return [
        RetentionPolicyResponse(
            id=str(p.id),
            record_category=p.record_category,
            retention_days=p.retention_days,
            legal_basis=p.legal_basis,
            statutory_rule=p.statutory_rule,
            action_on_expiry=p.action_on_expiry,
            description=p.description,
            is_active=p.is_active,
            updated_by=p.updated_by,
            updated_at=p.updated_at,
        )
        for p in policies
    ]


@router.put(
    "/retention-policies/{category}",
    response_model=RetentionPolicyResponse,
    summary="Update retention policy settings (AICTE Admin only)",
)
def update_retention_policy_endpoint(
    category: str,
    req: RetentionPolicyUpdateRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN)),
):
    """
    Updates retention duration, legal basis citation, and post-expiry action
    (PURGE, ANONYMIZE, ARCHIVE) for a record category.
    """
    pol = update_retention_policy(
        db=db,
        category=category,
        retention_days=req.retention_days,
        legal_basis=req.legal_basis,
        statutory_rule=req.statutory_rule,
        action_on_expiry=req.action_on_expiry,
        description=req.description,
        is_active=req.is_active,
        updated_by=user.user_id,
    )
    db.commit()

    return RetentionPolicyResponse(
        id=str(pol.id),
        record_category=pol.record_category,
        retention_days=pol.retention_days,
        legal_basis=pol.legal_basis,
        statutory_rule=pol.statutory_rule,
        action_on_expiry=pol.action_on_expiry,
        description=pol.description,
        is_active=pol.is_active,
        updated_by=pol.updated_by,
        updated_at=pol.updated_at,
    )
