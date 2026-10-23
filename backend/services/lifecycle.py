"""
Lifecycle State Machine Service (backend/services/lifecycle.py)

Implements the single source of truth for:
1. Enrollment State Machine:
   - Allowed transition table defined in ONE place.
   - Enforces caller's role.
   - Returns 409 with {code: "INVALID_TRANSITION", from, to, allowed: [...]} on violations.
   - Releasing a seat (WITHDRAWN/CANCELLED/MIGRATED/REJECTED) triggers seat count recalculation.
   - Reopening closed records ONLY permitted via an AICTE_ADMIN exceptional workflow with a reason.
2. Review Case State Machine:
   - Workflow: OPEN -> ASSIGNED -> AWAITING_INSTITUTION -> UNDER_DECISION -> RESOLVED | ESCALATED.
   - Institutions cannot approve their own exceptions.
"""
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from backend.models.audit import AuditEvent
from backend.models.enrollment import Enrollment
from backend.models.review import ReviewCase
from backend.models.version import RecordVersion
from backend.schemas.errors import AppException, BadRequestError, ForbiddenError
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
)
from backend.services.audit import record_audit_event
from backend.services.seat_compliance import calculate_approval_seat_compliance

logger = logging.getLogger("lifecycle")

# ---------------------------------------------------------------------------
# Enrollment Lifecycle States
# ---------------------------------------------------------------------------
STATUS_DRAFT = "DRAFT"
STATUS_PROVISIONAL = "PROVISIONAL"
STATUS_UNDER_REVIEW = "UNDER_REVIEW"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_WITHDRAWN = "WITHDRAWN"
STATUS_CANCELLED = "CANCELLED"
STATUS_MIGRATED = "MIGRATED"
STATUS_REJECTED = "REJECTED"
STATUS_DUPLICATE = "DUPLICATE"

ALL_ENROLLMENT_STATES = {
    STATUS_DRAFT,
    STATUS_PROVISIONAL,
    STATUS_UNDER_REVIEW,
    STATUS_CONFIRMED,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_WITHDRAWN,
    STATUS_CANCELLED,
    STATUS_MIGRATED,
    STATUS_REJECTED,
    STATUS_DUPLICATE,
}

# Terminal closed states: Can only be reopened by AICTE_ADMIN with mandatory exceptional_reason
CLOSED_TERMINAL_STATES = {
    STATUS_COMPLETED,
    STATUS_WITHDRAWN,
    STATUS_CANCELLED,
    STATUS_MIGRATED,
    STATUS_REJECTED,
}

# States that release an approved seat back to the institute
SEAT_RELEASING_STATES = {
    STATUS_WITHDRAWN,
    STATUS_CANCELLED,
    STATUS_MIGRATED,
    STATUS_REJECTED,
}

# The single source of truth for standard allowed transitions
ENROLLMENT_TRANSITIONS: Dict[str, Set[str]] = {
    STATUS_DRAFT: {STATUS_PROVISIONAL, STATUS_CANCELLED},
    STATUS_PROVISIONAL: {
        STATUS_CONFIRMED,
        STATUS_UNDER_REVIEW,
        STATUS_WITHDRAWN,
        STATUS_CANCELLED,
        STATUS_REJECTED,
        STATUS_DUPLICATE,
    },
    STATUS_UNDER_REVIEW: {
        STATUS_CONFIRMED,
        STATUS_PROVISIONAL,
        STATUS_REJECTED,
        STATUS_WITHDRAWN,
        STATUS_CANCELLED,
        STATUS_DUPLICATE,
    },
    STATUS_DUPLICATE: {
        STATUS_UNDER_REVIEW,
        STATUS_WITHDRAWN,
        STATUS_CANCELLED,
        STATUS_REJECTED,
    },
    STATUS_CONFIRMED: {
        STATUS_ACTIVE,
        STATUS_UNDER_REVIEW,
        STATUS_WITHDRAWN,
        STATUS_CANCELLED,
        STATUS_MIGRATED,
    },
    STATUS_ACTIVE: {
        STATUS_COMPLETED,
        STATUS_UNDER_REVIEW,
        STATUS_WITHDRAWN,
        STATUS_CANCELLED,
        STATUS_MIGRATED,
    },
    # Closed terminal states have NO standard allowed transitions
    STATUS_COMPLETED: set(),
    STATUS_WITHDRAWN: set(),
    STATUS_CANCELLED: set(),
    STATUS_MIGRATED: set(),
    STATUS_REJECTED: set(),
}


# ---------------------------------------------------------------------------
# Review Case Types & Lifecycle Workflow
# ---------------------------------------------------------------------------
REVIEW_TYPE_DUPLICATE = "DUPLICATE"
REVIEW_TYPE_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
REVIEW_TYPE_SEAT_EXCEPTION = "SEAT_EXCEPTION"
REVIEW_TYPE_APPROVAL_MISMATCH = "APPROVAL_MISMATCH"
REVIEW_TYPE_MISSING_IDENTIFIER = "MISSING_IDENTIFIER"
REVIEW_TYPE_LATE_SUBMISSION = "LATE_SUBMISSION"
REVIEW_TYPE_CORRECTION_REQUEST = "CORRECTION_REQUEST"

ALL_REVIEW_TYPES = {
    REVIEW_TYPE_DUPLICATE,
    REVIEW_TYPE_IDENTITY_MISMATCH,
    REVIEW_TYPE_SEAT_EXCEPTION,
    REVIEW_TYPE_APPROVAL_MISMATCH,
    REVIEW_TYPE_MISSING_IDENTIFIER,
    REVIEW_TYPE_LATE_SUBMISSION,
    REVIEW_TYPE_CORRECTION_REQUEST,
}

CASE_STATUS_OPEN = "OPEN"
CASE_STATUS_ASSIGNED = "ASSIGNED"
CASE_STATUS_AWAITING_INSTITUTION = "AWAITING_INSTITUTION"
CASE_STATUS_UNDER_DECISION = "UNDER_DECISION"
CASE_STATUS_RESOLVED = "RESOLVED"
CASE_STATUS_ESCALATED = "ESCALATED"

ALL_CASE_STATUSES = {
    CASE_STATUS_OPEN,
    CASE_STATUS_ASSIGNED,
    CASE_STATUS_AWAITING_INSTITUTION,
    CASE_STATUS_UNDER_DECISION,
    CASE_STATUS_RESOLVED,
    CASE_STATUS_ESCALATED,
}

REVIEW_CASE_TRANSITIONS: Dict[str, Set[str]] = {
    CASE_STATUS_OPEN: {
        CASE_STATUS_ASSIGNED,
        CASE_STATUS_AWAITING_INSTITUTION,
        CASE_STATUS_UNDER_DECISION,
        CASE_STATUS_RESOLVED,
        CASE_STATUS_ESCALATED,
    },
    CASE_STATUS_ASSIGNED: {
        CASE_STATUS_AWAITING_INSTITUTION,
        CASE_STATUS_UNDER_DECISION,
        CASE_STATUS_RESOLVED,
        CASE_STATUS_ESCALATED,
    },
    CASE_STATUS_AWAITING_INSTITUTION: {
        CASE_STATUS_UNDER_DECISION,
        CASE_STATUS_ESCALATED,
    },
    CASE_STATUS_UNDER_DECISION: {
        CASE_STATUS_RESOLVED,
        CASE_STATUS_AWAITING_INSTITUTION,
        CASE_STATUS_ESCALATED,
    },
    CASE_STATUS_RESOLVED: set(),  # Terminal
    CASE_STATUS_ESCALATED: {
        CASE_STATUS_UNDER_DECISION,
        CASE_STATUS_RESOLVED,
    },
}

# Review Decisions
DECISION_DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"
DECISION_LEGITIMATE_SEPARATE_ENROLMENT = "LEGITIMATE_SEPARATE_ENROLMENT"
DECISION_WITHDRAW_ONE_RECORD = "WITHDRAW_ONE_RECORD"
DECISION_CONFIRM = "CONFIRM"
DECISION_REJECT = "REJECT"
DECISION_ESCALATE = "ESCALATE"

ALL_REVIEW_DECISIONS = {
    DECISION_DATA_ENTRY_ERROR,
    DECISION_LEGITIMATE_SEPARATE_ENROLMENT,
    DECISION_WITHDRAW_ONE_RECORD,
    DECISION_CONFIRM,
    DECISION_REJECT,
    DECISION_ESCALATE,
}


# ---------------------------------------------------------------------------
# Custom Exception for Invalid State Transitions
# ---------------------------------------------------------------------------
class InvalidTransitionError(AppException):
    """
    HTTP 409 Conflict when an invalid state transition is attempted.
    Must return: {code: "INVALID_TRANSITION", from, to, allowed: [...]}
    """
    def __init__(self, from_state: str, to_state: str, allowed: List[str], reason: str = ""):
        details = {
            "from": from_state,
            "to": to_state,
            "allowed": sorted(allowed),
        }
        if reason:
            details["reason"] = reason

        super().__init__(
            code="INVALID_TRANSITION",
            message=f"Transition from '{from_state}' to '{to_state}' is not permitted. {reason}".strip(),
            status_code=409,
            field="status",
            details=details,
        )


# ---------------------------------------------------------------------------
# Enrollment State Machine Implementation
# ---------------------------------------------------------------------------
def transition_enrollment_status(
    db: Session,
    enrollment: Enrollment,
    target_status: str,
    actor_id: str,
    actor_role: str,
    reason: Optional[str] = None,
    exceptional_reason: Optional[str] = None,
) -> Enrollment:
    """
    Transitions an enrollment to target_status, strictly enforcing:
    1. Allowed transition table in ONE place.
    2. Caller role permissions.
    3. Closed record reopening ONLY via AICTE_ADMIN with mandatory exceptional_reason.
    4. Recalculates seat counts on seat-releasing transitions (WITHDRAWN/CANCELLED/MIGRATED).
    5. Creates RecordVersion snapshot and logs AuditEvent.
    """
    current_status = (enrollment.status or STATUS_PROVISIONAL).upper()
    target = target_status.strip().upper()

    if target not in ALL_ENROLLMENT_STATES:
        raise BadRequestError(f"Target status '{target}' is not a recognized enrollment status.")

    # Idempotent: same state transition is a no-op
    if target == current_status:
        return enrollment

    # Check caller role general authorization
    if actor_role in (ROLE_STUDENT, ROLE_AUDITOR):
        raise ForbiddenError(f"Role '{actor_role}' is not authorized to modify enrollment lifecycle status.")

    # 1. Closed Terminal State Reopening Check
    if current_status in CLOSED_TERMINAL_STATES:
        if actor_role != ROLE_AICTE_ADMIN:
            raise ForbiddenError(
                f"Cannot modify closed record in '{current_status}' status. "
                f"Reopening closed records is exclusively restricted to AICTE_ADMIN."
            )
        if not exceptional_reason or not exceptional_reason.strip():
            raise BadRequestError(
                f"Exceptional reopening of closed record '{enrollment.id}' from status "
                f"'{current_status}' requires a mandatory 'exceptional_reason'."
            )

        # AICTE_ADMIN exceptional workflow permits reopening into PROVISIONAL, UNDER_REVIEW, or CONFIRMED
        allowed_reopen_targets = {STATUS_PROVISIONAL, STATUS_UNDER_REVIEW, STATUS_CONFIRMED, STATUS_ACTIVE}
        if target not in allowed_reopen_targets:
            raise InvalidTransitionError(
                from_state=current_status,
                to_state=target,
                allowed=list(allowed_reopen_targets),
                reason="Closed records can only be exceptionally reopened to PROVISIONAL, UNDER_REVIEW, CONFIRMED, or ACTIVE.",
            )

    else:
        # 2. Standard Transition Check
        allowed = ENROLLMENT_TRANSITIONS.get(current_status, set())
        if target not in allowed:
            raise InvalidTransitionError(
                from_state=current_status,
                to_state=target,
                allowed=list(allowed),
                reason=f"Status '{current_status}' does not allow transition to '{target}'.",
            )

        # 3. Role-Specific Restrictions
        if actor_role in (ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR):
            # Institutions cannot resolve exceptions or self-approve review cases
            if current_status == STATUS_UNDER_REVIEW and target in (STATUS_CONFIRMED, STATUS_ACTIVE):
                raise ForbiddenError("Institutions cannot approve or confirm records under review.")
            # Institutions can only withdraw, cancel, migrate, or submit draft
            allowed_for_inst = {STATUS_PROVISIONAL, STATUS_WITHDRAWN, STATUS_CANCELLED, STATUS_MIGRATED}
            if target not in allowed_for_inst:
                raise ForbiddenError(
                    f"Institution roles cannot transition enrollment to '{target}'. "
                    f"Permitted: {sorted(list(allowed_for_inst))}"
                )

    # 4. Capture Before Snapshot
    previous_snapshot = {
        "status": current_status,
        "verified": enrollment.verified,
        "identity_status": enrollment.identity_status,
        "authority_status": enrollment.authority_status,
        "compliance_status": enrollment.compliance_status,
        "version": enrollment.version,
    }

    # 5. Apply State Change & Consequence
    enrollment.status = target

    if target == STATUS_CONFIRMED:
        enrollment.verified = True
    elif target in SEAT_RELEASING_STATES:
        enrollment.verified = False

    enrollment.version = (enrollment.version or 1) + 1

    # 6. Record Version Snapshot
    effective_reason = exceptional_reason or reason or f"Lifecycle transition: {current_status} -> {target}"
    version_rec = RecordVersion(
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        version=enrollment.version,
        snapshot={
            "before": previous_snapshot,
            "after": {
                "status": target,
                "verified": enrollment.verified,
                "version": enrollment.version,
            },
            "reason": effective_reason,
            "actor_role": actor_role,
        },
        change_reason=effective_reason,
        actor_id=actor_id,
    )
    db.add(version_rec)

    # 7. Releasing a seat recalculates seat compliance
    if target in SEAT_RELEASING_STATES or current_status in SEAT_RELEASING_STATES:
        try:
            calculate_approval_seat_compliance(db=db, approval_id=enrollment.approval_id)
            logger.info(f"Recalculated seat compliance for approval '{enrollment.approval_id}' following status '{target}'")
        except Exception as exc:
            logger.warning(f"Seat compliance recalculation notice: {exc}")

    # 7b. Auto-revoke active credentials when enrollment becomes REJECTED, CANCELLED, or WITHDRAWN
    if target in (STATUS_REJECTED, STATUS_CANCELLED, STATUS_WITHDRAWN):
        try:
            from backend.services.credential_service import auto_revoke_credential_for_enrollment
            auto_revoke_credential_for_enrollment(
                db=db,
                enrollment_id=str(enrollment.id),
                trigger_status=target,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.warning(f"Auto-revocation check notice for enrollment '{enrollment.id}': {exc}")

    # 8. Audit Event
    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="ENROLLMENT_STATUS_CHANGE",
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        reason=effective_reason,
    )

    db.flush()
    return enrollment


# ---------------------------------------------------------------------------
# Review Case State Machine Implementation
# ---------------------------------------------------------------------------
def transition_review_case_status(
    db: Session,
    case: ReviewCase,
    target_status: str,
    actor_id: str,
    actor_role: str,
    reason: Optional[str] = None,
) -> ReviewCase:
    """
    Transitions a review case through its workflow:
    OPEN -> ASSIGNED -> AWAITING_INSTITUTION -> UNDER_DECISION -> RESOLVED | ESCALATED.
    Enforces that institutions cannot resolve or decide cases.
    """
    current_status = (case.status or CASE_STATUS_OPEN).upper()
    target = target_status.strip().upper()

    if target not in ALL_CASE_STATUSES:
        raise BadRequestError(f"Target case status '{target}' is not recognized.")

    if target == current_status:
        return case

    allowed = REVIEW_CASE_TRANSITIONS.get(current_status, set())
    if target not in allowed:
        raise InvalidTransitionError(
            from_state=current_status,
            to_state=target,
            allowed=list(allowed),
            reason=f"Review case status '{current_status}' does not allow transition to '{target}'.",
        )

    # Role enforcement: Institutions cannot decide or resolve
    if actor_role in (ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR):
        if target in (CASE_STATUS_RESOLVED, CASE_STATUS_ESCALATED):
            raise ForbiddenError("Institutions cannot decide, resolve, or escalate review cases.")

    case.status = target

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="REVIEW_CASE_STATUS_CHANGE",
        entity_type="REVIEW_CASE",
        entity_id=str(case.id),
        reason=reason or f"Review case transitioned from {current_status} to {target}",
    )

    db.flush()
    return case
