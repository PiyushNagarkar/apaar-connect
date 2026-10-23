"""
Audit Service (backend/services/audit_service.py).

Implements:
1. Append-only tamper-evident audit logging for every write state change.
2. Cryptographic SHA-256 hash chaining: hash = SHA256(prev_hash + canonical_event).
3. Verification of audit hash chains from genesis to tail (detects altered/deleted links).
4. Querying audit events with granular filters (actor, institution, entity, action, time).
5. Configurable retention-policy table management (rejected / withdrawn / duplicate records).
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.models.audit import AuditEvent
from backend.models.retention import RetentionPolicy
from backend.schemas.errors import BadRequestError, NotFoundError

logger = logging.getLogger("audit_service")

GENESIS_HASH = "GENESIS_ROOT_AICTE_APAAR_AUDIT_V1"

DEFAULT_RETENTION_POLICIES = [
    {
        "record_category": "REJECTED",
        "retention_days": 2555,  # 7 years
        "legal_basis": "AICTE Approval Process Handbook (APH) 2024-25 Clause 6.4",
        "statutory_rule": "RULE_RETENTION_REJECTED_APPLICATIONS",
        "action_on_expiry": "PURGE",
        "description": "Retention mandate for rejected admissions and non-approved application filings.",
    },
    {
        "record_category": "WITHDRAWN",
        "retention_days": 1825,  # 5 years
        "legal_basis": "AICTE Admission Regulation & DPDP Act 2023 Section 7",
        "statutory_rule": "RULE_RETENTION_WITHDRAWN_ADMISSIONS",
        "action_on_expiry": "ANONYMIZE",
        "description": "Statutory retention for student records post-withdrawal for fee reconciliation and seat accounting.",
    },
    {
        "record_category": "DUPLICATE",
        "retention_days": 1095,  # 3 years
        "legal_basis": "Central Admission Integrity Protocol & Anti-Fraud Guidelines",
        "statutory_rule": "RULE_RETENTION_DUPLICATE_CANDIDATES",
        "action_on_expiry": "ARCHIVE",
        "description": "Retention for resolved duplicate candidates and synthetic cross-institution conflict logs.",
    },
    {
        "record_category": "UNRESOLVED_EXCEPTIONS",
        "retention_days": 3650,  # 10 years
        "legal_basis": "Statutory Adjudication & Regulatory Compliance Records Mandate",
        "statutory_rule": "RULE_RETENTION_UNRESOLVED_DISPUTES",
        "action_on_expiry": "ARCHIVE",
        "description": "Active retention for disputed enrollments, seat overages, and escalated review cases.",
    },
]


# ---------------------------------------------------------------------------
# 1. Tamper-Evident Hash Chain Computation
# ---------------------------------------------------------------------------
def canonical_event_json(event_payload: Dict[str, Any]) -> str:
    """Serializes audit payload deterministically with sorted keys for cryptographic hashing."""
    return json.dumps(event_payload, sort_keys=True, separators=(",", ":"), default=str)


def calculate_audit_hash(prev_hash: Optional[str], event_payload: Dict[str, Any]) -> str:
    """
    Computes cryptographic SHA-256 hash:
    hash = SHA256(prev_hash + canonical_event_payload).
    """
    effective_prev = prev_hash or GENESIS_HASH
    serialized = canonical_event_json(event_payload)
    chain_input = f"{effective_prev}:{serialized}".encode("utf-8")
    return hashlib.sha256(chain_input).hexdigest()


def record_audit_event(
    db: Session,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    reason: str,
    request_id: Optional[str] = None,
    institution_id: Optional[str] = None,
) -> AuditEvent:
    """
    Records an append-only audit event with cryptographic link to previous event.
    Enforces Rule 9: Every write action writes an audit event.
    """
    resolved_req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"

    # Fetch last event to chain hashes
    last_event = db.query(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).first()
    prev_hash = last_event.hash if last_event else GENESIS_HASH

    event_payload = {
        "actor_id": actor_id,
        "institution_id": institution_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "reason": reason,
        "request_id": resolved_req_id,
    }
    event_hash = calculate_audit_hash(prev_hash, event_payload)

    event = AuditEvent(
        actor_id=actor_id,
        institution_id=institution_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        reason=reason,
        request_id=resolved_req_id,
        prev_hash=prev_hash,
        hash=event_hash,
    )
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------------------
# 2. Filtered Event Retrieval (GET /api/audit-events)
# ---------------------------------------------------------------------------
def get_audit_events(
    db: Session,
    actor_id: Optional[str] = None,
    institution_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[AuditEvent]:
    """Retrieves audit events with comprehensive regulatory filters."""
    q = db.query(AuditEvent)

    if actor_id:
        q = q.filter(AuditEvent.actor_id == actor_id)
    if institution_id:
        q = q.filter(AuditEvent.institution_id == institution_id)
    if entity_type:
        q = q.filter(AuditEvent.entity_type == entity_type.strip().upper())
    if entity_id:
        q = q.filter(AuditEvent.entity_id == str(entity_id))
    if action:
        q = q.filter(AuditEvent.action == action.strip().upper())
    if start_time:
        q = q.filter(AuditEvent.created_at >= start_time)
    if end_time:
        q = q.filter(AuditEvent.created_at <= end_time)

    return q.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit).all()


# ---------------------------------------------------------------------------
# 3. Hash Chain Integrity Verification (verify-chain algorithm)
# ---------------------------------------------------------------------------
def verify_audit_hash_chain(db: Session, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Verifies cryptographic integrity of the entire audit chain:
    - Checks that row[i].prev_hash == row[i-1].hash.
    - Recalculates expected hash over payload.
    - Flags any altered or deleted records.
    """
    q = db.query(AuditEvent).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    if limit:
        q = q.limit(limit)
    events = q.all()

    if not events:
        return {
            "chain_valid": True,
            "total_events_checked": 0,
            "genesis_hash": None,
            "tail_hash": None,
            "broken_links": [],
        }

    broken_links: List[Dict[str, Any]] = []
    expected_prev = GENESIS_HASH

    for idx, evt in enumerate(events):
        # 1. Verify link to previous event
        if evt.prev_hash != expected_prev:
            broken_links.append({
                "event_index": idx,
                "event_id": str(evt.id),
                "issue": "PREV_HASH_MISMATCH",
                "expected_prev_hash": expected_prev,
                "actual_prev_hash": evt.prev_hash,
            })

        # 2. Recompute expected hash
        payload = {
            "actor_id": evt.actor_id,
            "institution_id": evt.institution_id,
            "action": evt.action,
            "entity_type": evt.entity_type,
            "entity_id": str(evt.entity_id),
            "reason": evt.reason,
            "request_id": evt.request_id,
        }
        recomputed = calculate_audit_hash(evt.prev_hash, payload)
        if evt.hash != recomputed:
            broken_links.append({
                "event_index": idx,
                "event_id": str(evt.id),
                "issue": "EVENT_HASH_TAMPERED",
                "expected_hash": recomputed,
                "stored_hash": evt.hash,
            })

        expected_prev = evt.hash

    return {
        "chain_valid": len(broken_links) == 0,
        "total_events_checked": len(events),
        "genesis_hash": events[0].hash,
        "tail_hash": events[-1].hash,
        "broken_links": broken_links,
    }


# ---------------------------------------------------------------------------
# 4. Configurable Retention Policies
# ---------------------------------------------------------------------------
def seed_default_retention_policies(db: Session) -> None:
    """Initializes default retention policies in DB if table is empty."""
    for item in DEFAULT_RETENTION_POLICIES:
        existing = db.query(RetentionPolicy).filter(
            RetentionPolicy.record_category == item["record_category"]
        ).first()
        if not existing:
            pol = RetentionPolicy(
                record_category=item["record_category"],
                retention_days=item["retention_days"],
                legal_basis=item["legal_basis"],
                statutory_rule=item["statutory_rule"],
                action_on_expiry=item["action_on_expiry"],
                description=item["description"],
                is_active=True,
            )
            db.add(pol)
    db.flush()


def get_retention_policies(db: Session) -> List[RetentionPolicy]:
    """Retrieves all retention policies, automatically initializing defaults."""
    seed_default_retention_policies(db)
    return db.query(RetentionPolicy).order_by(RetentionPolicy.retention_days.desc()).all()


def update_retention_policy(
    db: Session,
    category: str,
    retention_days: int,
    legal_basis: Optional[str] = None,
    statutory_rule: Optional[str] = None,
    action_on_expiry: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    updated_by: str = "ADMIN",
) -> RetentionPolicy:
    """Updates a configurable retention policy."""
    clean_cat = category.strip().upper()
    pol = db.query(RetentionPolicy).filter(RetentionPolicy.record_category == clean_cat).first()
    if not pol:
        # Create if not existing
        pol = RetentionPolicy(
            record_category=clean_cat,
            retention_days=retention_days,
            legal_basis=legal_basis or "Statutory Regulatory Mandate",
            statutory_rule=statutory_rule,
            action_on_expiry=action_on_expiry or "PURGE",
            description=description,
            is_active=True if is_active is None else is_active,
            updated_by=updated_by,
        )
        db.add(pol)
    else:
        pol.retention_days = retention_days
        if legal_basis is not None:
            pol.legal_basis = legal_basis
        if statutory_rule is not None:
            pol.statutory_rule = statutory_rule
        if action_on_expiry is not None:
            pol.action_on_expiry = action_on_expiry.strip().upper()
        if description is not None:
            pol.description = description
        if is_active is not None:
            pol.is_active = is_active
        pol.updated_by = updated_by

    record_audit_event(
        db=db,
        actor_id=updated_by,
        action="RETENTION_POLICY_UPDATED",
        entity_type="RETENTION_POLICY",
        entity_id=clean_cat,
        reason=f"Updated retention for '{clean_cat}' to {retention_days} days (action: {pol.action_on_expiry})",
    )
    db.flush()

    logger.info(f"Updated retention policy '{clean_cat}': {retention_days} days by {updated_by}")
    return pol
