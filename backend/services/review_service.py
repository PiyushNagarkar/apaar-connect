"""
Review Case & Correction Service (backend/services/review_service.py)

Manages:
1. Review Cases:
   - Types: DUPLICATE, IDENTITY_MISMATCH, SEAT_EXCEPTION, APPROVAL_MISMATCH,
            MISSING_IDENTIFIER, LATE_SUBMISSION, CORRECTION_REQUEST.
   - Workflow: OPEN -> ASSIGNED -> AWAITING_INSTITUTION -> UNDER_DECISION -> RESOLVED | ESCALATED.
   - Decisions: DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT, WITHDRAW_ONE_RECORD,
                CONFIRM, REJECT, ESCALATE.
   - Consequence applied to enrollment strictly via lifecycle state machine.
   - Evidence references + SHA-256 hash (never raw files).
   - SLA due dates by severity and overdue calculation.
2. Correction Requests:
   - Creates version N+1 of the record with before/after snapshot, reason code, and approver.
   - Old versions permanently retained.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.audit import AuditEvent
from backend.models.correction import CorrectionRequest
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.review import ReviewCase
from backend.models.student import Student
from backend.models.user import User
from backend.models.version import RecordVersion
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
)
from backend.services.audit import record_audit_event
from backend.services.lifecycle import (
    ALL_REVIEW_DECISIONS,
    ALL_REVIEW_TYPES,
    CASE_STATUS_ASSIGNED,
    CASE_STATUS_AWAITING_INSTITUTION,
    CASE_STATUS_ESCALATED,
    CASE_STATUS_OPEN,
    CASE_STATUS_RESOLVED,
    CASE_STATUS_UNDER_DECISION,
    DECISION_CONFIRM,
    DECISION_DATA_ENTRY_ERROR,
    DECISION_ESCALATE,
    DECISION_LEGITIMATE_SEPARATE_ENROLMENT,
    DECISION_REJECT,
    DECISION_WITHDRAW_ONE_RECORD,
    STATUS_CONFIRMED,
    STATUS_PROVISIONAL,
    STATUS_REJECTED,
    STATUS_UNDER_REVIEW,
    STATUS_WITHDRAWN,
    transition_enrollment_status,
    transition_review_case_status,
)

logger = logging.getLogger("review_service")

# ---------------------------------------------------------------------------
# SLA Configuration by Severity (in hours)
# ---------------------------------------------------------------------------
SLA_HOURS_BY_SEVERITY: Dict[str, int] = {
    "CRITICAL": 24,       # 1 day
    "REGULATORY_ALERT": 24,
    "HIGH": 48,           # 2 days
    "MEDIUM": 168,        # 7 days
    "LOW": 336,           # 14 days
}


def calculate_due_date(severity: str, start_time: Optional[datetime] = None) -> datetime:
    """Calculates SLA due_at timestamp based on case severity."""
    now = start_time or datetime.now(timezone.utc)
    hours = SLA_HOURS_BY_SEVERITY.get(severity.upper(), 72)
    return now + timedelta(hours=hours)


def is_case_overdue(case: ReviewCase) -> bool:
    """Returns True if the review case is open and past its SLA due_at deadline."""
    if case.status in (CASE_STATUS_RESOLVED, "CLOSED"):
        return False
    if not case.due_at:
        return False
    now = datetime.now(timezone.utc)
    case_due = case.due_at if case.due_at.tzinfo else case.due_at.replace(tzinfo=timezone.utc)
    return now > case_due


def calculate_hours_remaining(case: ReviewCase) -> Optional[float]:
    """Computes hours remaining before SLA breach (negative if overdue)."""
    if not case.due_at:
        return None
    now = datetime.now(timezone.utc)
    case_due = case.due_at if case.due_at.tzinfo else case.due_at.replace(tzinfo=timezone.utc)
    diff = (case_due - now).total_seconds() / 3600.0
    return round(diff, 1)


# ---------------------------------------------------------------------------
# Review Case Operations
# ---------------------------------------------------------------------------
def create_review_case(
    db: Session,
    type_str: str,
    enrollment_id: str,
    severity: str = "MEDIUM",
    priority: Optional[float] = None,
    evidence: Optional[Dict[str, Any]] = None,
    assigned_to: Optional[str] = None,
    actor_id: str = "SYSTEM",
) -> ReviewCase:
    """Creates a new ReviewCase with SLA due_at and audit trail."""
    type_upper = type_str.upper()
    if type_upper not in ALL_REVIEW_TYPES and not type_upper.startswith("RULE_"):
        raise BadRequestError(f"Review case type '{type_str}' is invalid. Allowed: {sorted(list(ALL_REVIEW_TYPES))}")

    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment '{enrollment_id}' not found.")

    default_priorities = {
        "CRITICAL": 95.0,
        "REGULATORY_ALERT": 90.0,
        "HIGH": 85.0,
        "MEDIUM": 65.0,
        "LOW": 40.0,
    }
    prio = priority if priority is not None else default_priorities.get(severity.upper(), 50.0)
    due_at = calculate_due_date(severity)

    case = ReviewCase(
        type=type_upper,
        severity=severity.upper(),
        priority=prio,
        enrollment_id=enrollment.id,
        institution_id=enrollment.institution_id,
        assigned_to=assigned_to,
        status=CASE_STATUS_ASSIGNED if assigned_to else CASE_STATUS_OPEN,
        evidence=evidence or {"items": []},
        due_at=due_at,
    )
    db.add(case)
    db.flush()

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="REVIEW_CASE_CREATE",
        entity_type="REVIEW_CASE",
        entity_id=str(case.id),
        reason=f"Opened review case type '{type_upper}' for enrollment '{enrollment.id}' with SLA due {due_at.isoformat()}",
    )
    db.flush()
    return case


def assign_review_case(
    db: Session,
    case_id: str,
    assignee_id: str,
    actor_id: str,
    actor_role: str,
) -> ReviewCase:
    """Assigns review case to an AICTE reviewer and updates workflow status to ASSIGNED."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    # Institutions cannot self-assign review cases
    if actor_role in (ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR):
        raise ForbiddenError("Institution roles cannot assign review cases.")

    assignee = db.query(User).filter(User.id == assignee_id).first()
    if not assignee:
        raise NotFoundError(f"Assignee user '{assignee_id}' not found.")

    if case.status == CASE_STATUS_OPEN:
        transition_review_case_status(
            db=db,
            case=case,
            target_status=CASE_STATUS_ASSIGNED,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"Assigned case to reviewer '{assignee.email or assignee_id}'",
        )

    case.assigned_to = assignee_id
    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="REVIEW_CASE_ASSIGN",
        entity_type="REVIEW_CASE",
        entity_id=str(case.id),
        reason=f"Assigned case to '{assignee_id}'",
    )
    db.flush()
    return case


def attach_evidence_reference(
    db: Session,
    case_id: str,
    evidence_ref: str,
    evidence_hash: str,
    description: Optional[str],
    actor_id: str,
    actor_role: str,
) -> ReviewCase:
    """
    Attaches evidence reference + SHA-256 hash (never raw document binary).
    If case was awaiting institution response, automatically advances to UNDER_DECISION.
    """
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    # Validate SHA-256 hash format (64 hex characters)
    clean_hash = evidence_hash.strip().lower()
    if not re.match(r"^[a-f0-9]{64}$", clean_hash):
        raise BadRequestError(
            f"Invalid evidence_hash: must be a valid 64-character hex SHA-256 digest."
        )

    evidence_dict = dict(case.evidence or {})
    items = list(evidence_dict.get("items", []))

    new_item = {
        "evidence_ref": evidence_ref.strip(),
        "evidence_hash": clean_hash,
        "description": description or "Institutional clarification document reference",
        "submitted_by": actor_id,
        "submitted_role": actor_role,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    items.append(new_item)
    evidence_dict["items"] = items
    case.evidence = evidence_dict

    # If case was AWAITING_INSTITUTION, institution submission moves it to UNDER_DECISION
    if case.status == CASE_STATUS_AWAITING_INSTITUTION:
        transition_review_case_status(
            db=db,
            case=case,
            target_status=CASE_STATUS_UNDER_DECISION,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"Institution submitted clarification evidence: ref '{evidence_ref}'",
        )

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="REVIEW_CASE_EVIDENCE_ATTACH",
        entity_type="REVIEW_CASE",
        entity_id=str(case.id),
        reason=f"Attached evidence ref '{evidence_ref}' (sha256:{clean_hash[:12]}...)",
    )
    db.flush()
    return case


def decide_review_case(
    db: Session,
    case_id: str,
    decision: str,
    decision_reason: str,
    actor_id: str,
    actor_role: str,
) -> ReviewCase:
    """
    Decides a review case:
    Decisions: DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT, WITHDRAW_ONE_RECORD,
               CONFIRM, REJECT, ESCALATE.
    Consequences applied strictly via lifecycle state machine (not by direct DB edits).
    Institutions CANNOT decide review cases.
    """
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    dec_upper = decision.strip().upper()
    if dec_upper not in ALL_REVIEW_DECISIONS:
        raise BadRequestError(f"Decision '{decision}' is invalid. Allowed: {sorted(list(ALL_REVIEW_DECISIONS))}")

    if not decision_reason or not decision_reason.strip():
        raise BadRequestError("A mandatory 'decision_reason' is required to decide a review case.")

    # Rule: Institutions cannot approve their own exceptions!
    if actor_role in (ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR):
        raise ForbiddenError("Institution roles are strictly forbidden from deciding review cases.")

    # Workflow transition
    target_case_status = CASE_STATUS_ESCALATED if dec_upper == DECISION_ESCALATE else CASE_STATUS_RESOLVED
    transition_review_case_status(
        db=db,
        case=case,
        target_status=target_case_status,
        actor_id=actor_id,
        actor_role=actor_role,
        reason=f"Decided: {dec_upper} - {decision_reason}",
    )

    case.decision = dec_upper
    case.decision_reason = decision_reason.strip()

    # Apply consequences to the enrollment via lifecycle state machine
    enrollment = case.enrollment
    if enrollment:
        if dec_upper == DECISION_CONFIRM:
            transition_enrollment_status(
                db=db,
                enrollment=enrollment,
                target_status=STATUS_CONFIRMED,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Review Case '{case.id}' Confirmed: {decision_reason}",
            )
        elif dec_upper == DECISION_REJECT:
            transition_enrollment_status(
                db=db,
                enrollment=enrollment,
                target_status=STATUS_REJECTED,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Review Case '{case.id}' Rejected: {decision_reason}",
            )
        elif dec_upper == DECISION_WITHDRAW_ONE_RECORD:
            transition_enrollment_status(
                db=db,
                enrollment=enrollment,
                target_status=STATUS_WITHDRAWN,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Review Case '{case.id}' Withdrawn: {decision_reason}",
            )
        elif dec_upper == DECISION_DATA_ENTRY_ERROR:
            # Allows correction workflow
            transition_enrollment_status(
                db=db,
                enrollment=enrollment,
                target_status=STATUS_PROVISIONAL,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Review Case '{case.id}' Marked for correction (DATA_ENTRY_ERROR): {decision_reason}",
            )
        elif dec_upper == DECISION_LEGITIMATE_SEPARATE_ENROLMENT:
            # Dismiss duplicate candidate and confirm
            dups = (
                db.query(DuplicateCandidate)
                .filter(
                    (DuplicateCandidate.enrollment_a == enrollment.id) |
                    (DuplicateCandidate.enrollment_b == enrollment.id)
                )
                .all()
            )
            for d in dups:
                d.status = "DISMISSED"
            transition_enrollment_status(
                db=db,
                enrollment=enrollment,
                target_status=STATUS_CONFIRMED,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Legitimate separate enrollment confirmed: {decision_reason}",
            )
        elif dec_upper == DECISION_ESCALATE:
            logger.info(f"Review Case '{case.id}' escalated; enrollment remains under review.")

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="REVIEW_CASE_DECIDE",
        entity_type="REVIEW_CASE",
        entity_id=str(case.id),
        reason=f"Applied decision '{dec_upper}': {decision_reason}",
    )
    db.flush()
    return case


def get_review_case_history(db: Session, case_id: str) -> List[Dict[str, Any]]:
    """Gathers complete chronological history for a review case."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise NotFoundError(f"Review case '{case_id}' not found.")

    audits = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "REVIEW_CASE",
            AuditEvent.entity_id == str(case.id),
        )
        .order_by(AuditEvent.created_at.asc())
        .all()
    )

    history = []
    for a in audits:
        history.append({
            "event_id": str(a.id),
            "action": a.action,
            "actor_id": a.actor_id,
            "reason": a.reason,
            "timestamp": a.created_at.isoformat() if a.created_at else None,
        })
    return history


# ---------------------------------------------------------------------------
# Correction Request Operations
# ---------------------------------------------------------------------------
def create_correction_request(
    db: Session,
    enrollment_id: str,
    reason_code: str,
    explanation: str,
    proposed_changes: Dict[str, Any],
    actor_id: str,
    institution_id: str,
) -> CorrectionRequest:
    """Creates a correction request with snapshot of current state."""
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment '{enrollment_id}' not found.")

    student = enrollment.student
    previous_state = {
        "enrollment": {
            "seat_type": enrollment.seat_type,
            "category": enrollment.category,
            "academic_year": enrollment.academic_year,
            "status": enrollment.status,
            "version": enrollment.version,
        },
        "student": {
            "name": student.name if student else None,
            "dob": student.dob.strftime("%Y-%m-%d") if (student and student.dob) else None,
            "gender": student.gender if student else None,
        },
    }

    req = CorrectionRequest(
        enrollment_id=enrollment.id,
        institution_id=institution_id,
        requested_by=actor_id,
        status="PENDING",
        reason_code=reason_code.strip(),
        explanation=explanation.strip(),
        proposed_changes=proposed_changes,
        previous_state=previous_state,
    )
    db.add(req)
    db.flush()

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="CORRECTION_REQUEST_CREATE",
        entity_type="CORRECTION_REQUEST",
        entity_id=str(req.id),
        reason=f"Requested correction for enrollment '{enrollment_id}' ({reason_code})",
    )
    db.flush()
    return req


def decide_correction_request(
    db: Session,
    request_id: str,
    approve: bool,
    decision_reason: str,
    actor_id: str,
    actor_role: str,
) -> CorrectionRequest:
    """
    Approves or rejects a correction request.
    If approved, increments enrollment version to N+1, creates RecordVersion snapshot,
    and applies changes. Old version is permanently retained.
    Institutions cannot approve correction requests.
    """
    req = db.query(CorrectionRequest).filter(CorrectionRequest.id == request_id).first()
    if not req:
        raise NotFoundError(f"Correction request '{request_id}' not found.")

    if req.status != "PENDING":
        raise BadRequestError(f"Correction request '{request_id}' has already been decided ({req.status}).")

    if actor_role in (ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR):
        raise ForbiddenError("Institution roles cannot approve or decide correction requests.")

    now = datetime.now(timezone.utc)
    req.approved_by = actor_id
    req.decision_reason = decision_reason.strip()
    req.decided_at = now

    if not approve:
        req.status = "REJECTED"
        record_audit_event(
            db=db,
            actor_id=actor_id,
            action="CORRECTION_REQUEST_REJECT",
            entity_type="CORRECTION_REQUEST",
            entity_id=str(req.id),
            reason=f"Rejected correction request: {decision_reason}",
        )
        db.flush()
        return req

    # Approval Workflow: Apply changes and create Version N+1
    req.status = "APPROVED"
    enrollment = req.enrollment
    student = enrollment.student if enrollment else None

    # Version N+1
    new_version = (enrollment.version or 1) + 1
    enrollment.version = new_version
    req.version_created = new_version

    changes = req.proposed_changes or {}

    # Apply student changes
    if student:
        if "name" in changes:
            student.name = changes["name"]
            student.name_normalized = changes["name"].strip().upper()
        if "dob" in changes:
            try:
                student.dob = datetime.strptime(changes["dob"], "%Y-%m-%d").date()
            except Exception:
                pass
        if "gender" in changes:
            student.gender = changes["gender"]

    # Apply enrollment changes
    if "seat_type" in changes:
        enrollment.seat_type = changes["seat_type"]
    if "category" in changes:
        enrollment.category = changes["category"]

    # RecordVersion snapshot (Rule 8: Version N+1 with before/after snapshots)
    record_version = RecordVersion(
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        version=new_version,
        snapshot={
            "before": req.previous_state,
            "after": {
                "enrollment": {
                    "seat_type": enrollment.seat_type,
                    "category": enrollment.category,
                    "version": new_version,
                },
                "student": {
                    "name": student.name if student else None,
                    "dob": student.dob.strftime("%Y-%m-%d") if (student and student.dob) else None,
                },
            },
            "changes": changes,
            "reason_code": req.reason_code,
            "explanation": req.explanation,
            "decision_reason": decision_reason,
            "approved_by": actor_id,
        },
        change_reason=f"Correction Request {req.id} ({req.reason_code}): {decision_reason}",
        actor_id=actor_id,
    )
    db.add(record_version)

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="CORRECTION_REQUEST_APPROVE",
        entity_type="CORRECTION_REQUEST",
        entity_id=str(req.id),
        reason=f"Approved correction request; created version {new_version}",
    )
    db.flush()
    return req
