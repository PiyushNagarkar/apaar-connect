"""
Privacy Service (backend/services/privacy_service.py).

Implements:
1. Consent Management:
   - Tracks consent_status: GRANTED | PENDING | WITHDRAWN | NOT_REQUIRED.
   - Purposes: ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING.
   - Separate from 'regulatory processing basis' records.
   - Verification and employer views honour consent: on WITHDRAWN stop external sharing
     but retain legally required records and state statutory retention notice.
   - Student can toggle consent and initiate correction requests.
2. Access Event Logging:
   - Log every read of a sensitive record (who, what, why/purpose, when).
   - Auditor and admin query access.
"""
from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.models.access_event import AccessEvent
from backend.models.consent import ConsentRecord, ProcessingBasisRecord
from backend.models.student import Student
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.services.audit import record_audit_event

logger = logging.getLogger("privacy_service")

VALID_CONSENT_STATUSES = {"GRANTED", "PENDING", "WITHDRAWN", "NOT_REQUIRED"}
VALID_PURPOSES = {"ADMISSION_REPORTING", "VERIFICATION", "REGULATORY_MONITORING"}
ALLOWED_CONSENT_STATUSES = VALID_CONSENT_STATUSES
ALLOWED_PURPOSES = VALID_PURPOSES

RETENTION_NOTICE_ON_WITHDRAWAL = (
    "Student consent has been withdrawn. External sharing is halted. "
    "Statutorily mandated admission records are retained pursuant to "
    "AICTE Act 1987 Section 10(k) and DPDP Act 2023 Section 7 compliance requirements."
)


# ---------------------------------------------------------------------------
# 1. Student Consent Operations
# ---------------------------------------------------------------------------
def record_consent(
    db: Session,
    student_id: str,
    purpose: str,
    consent_status: str,
    reference: Optional[str] = None,
    actor_id: str = "SYSTEM",
) -> ConsentRecord:
    """
    Records a student consent state: GRANTED | PENDING | WITHDRAWN | NOT_REQUIRED.
    Updates the student record's primary consent_status and appends a ConsentRecord.
    """
    clean_status = consent_status.strip().upper()
    clean_purpose = purpose.strip().upper()

    if clean_status not in VALID_CONSENT_STATUSES:
        raise BadRequestError(
            f"Invalid consent status '{consent_status}'. Must be one of {sorted(list(VALID_CONSENT_STATUSES))}."
        )

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise NotFoundError(f"Student '{student_id}' not found.")

    now = datetime.now(timezone.utc)
    ref = reference or f"CONSENT-REF-{uuid.uuid4().hex[:10].upper()}"

    consent = ConsentRecord(
        student_id=student.id,
        purpose=clean_purpose,
        status=clean_status,
        consent_status=clean_status,
        reference=ref,
        timestamp=now,
    )
    db.add(consent)

    # Sync Student entity's primary consent status
    student.consent_status = clean_status

    # Audit write event
    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="CONSENT_STATUS_RECORDED",
        entity_type="STUDENT_CONSENT",
        entity_id=student.id,
        reason=f"Recorded consent status '{clean_status}' for purpose '{clean_purpose}' (ref: {ref})",
    )
    db.flush()

    logger.info(f"Recorded consent '{clean_status}' for student '{student_id}' purpose '{clean_purpose}'")
    return consent


def get_consent_records(
    db: Session,
    student_id: Optional[str] = None,
    purpose: Optional[str] = None,
    consent_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ConsentRecord]:
    """Retrieves consent history filtered by student, purpose, or status."""
    q = db.query(ConsentRecord)
    if student_id:
        q = q.filter(ConsentRecord.student_id == student_id)
    if purpose:
        q = q.filter(ConsentRecord.purpose == purpose.strip().upper())
    if consent_status:
        q = q.filter(ConsentRecord.consent_status == consent_status.strip().upper())

    return q.order_by(ConsentRecord.timestamp.desc()).offset(offset).limit(limit).all()


def toggle_student_consent(
    db: Session,
    student_id: str,
    purpose: str,
    consent_status: str,
    actor_id: str = "STUDENT",
) -> Dict[str, Any]:
    """
    Enables student to toggle consent between GRANTED and WITHDRAWN.
    Returns status update and statutory retention notice.
    """
    rec = record_consent(
        db=db,
        student_id=student_id,
        purpose=purpose,
        consent_status=consent_status,
        actor_id=actor_id,
    )

    is_withdrawn = rec.consent_status == "WITHDRAWN"
    notice = RETENTION_NOTICE_ON_WITHDRAWAL if is_withdrawn else "Consent active for processing."

    return {
        "student_id": student_id,
        "purpose": rec.purpose,
        "consent_status": rec.consent_status,
        "external_sharing_permitted": not is_withdrawn,
        "notice": notice,
        "timestamp": rec.timestamp.isoformat(),
        "reference": rec.reference,
    }


# ---------------------------------------------------------------------------
# 2. Regulatory Processing Basis (Kept separate from consent)
# ---------------------------------------------------------------------------
def record_processing_basis(
    db: Session,
    basis_type: str,
    statute_reference: str,
    purpose: str,
    description: str,
    institution_id: Optional[str] = None,
    student_id: Optional[str] = None,
    valid_from: Optional[datetime] = None,
    valid_until: Optional[datetime] = None,
    actor_id: str = "SYSTEM",
) -> ProcessingBasisRecord:
    """
    Registers a legal/regulatory processing basis.
    Rule: Kept separate from student consent as a distinct record type.
    """
    now = datetime.now(timezone.utc)
    basis = ProcessingBasisRecord(
        institution_id=institution_id,
        student_id=student_id,
        basis_type=basis_type.strip().upper(),
        statute_reference=statute_reference.strip(),
        purpose=purpose.strip().upper(),
        description=description.strip(),
        valid_from=valid_from or now,
        valid_until=valid_until,
        is_active=True,
        created_by=actor_id,
    )
    db.add(basis)

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="PROCESSING_BASIS_RECORDED",
        entity_type="PROCESSING_BASIS",
        entity_id=str(basis.id),
        reason=f"Registered statutory basis '{basis.basis_type}': {basis.statute_reference} for {basis.purpose}",
    )
    db.flush()

    logger.info(f"Registered processing basis '{basis.id}' ({basis.statute_reference})")
    return basis


def get_processing_basis_records(
    db: Session,
    institution_id: Optional[str] = None,
    purpose: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ProcessingBasisRecord]:
    """Retrieves active regulatory processing basis records."""
    q = db.query(ProcessingBasisRecord)
    if institution_id:
        q = q.filter((ProcessingBasisRecord.institution_id == institution_id) | (ProcessingBasisRecord.institution_id == None))
    if purpose:
        q = q.filter(ProcessingBasisRecord.purpose == purpose.strip().upper())
    if is_active is not None:
        q = q.filter(ProcessingBasisRecord.is_active == is_active)

    return q.order_by(ProcessingBasisRecord.valid_from.desc()).offset(offset).limit(limit).all()


def check_external_sharing_consent(
    db: Session,
    student_id: str,
    purpose: str = "VERIFICATION",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Evaluates whether external sharing (e.g. verification, employer views) is allowed.
    On WITHDRAWN: stops external sharing but provides statutory retention justification.
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return False, "Student not found.", None

    # Check latest student consent record for this purpose
    latest_consent = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.timestamp.desc())
        .first()
    )

    consent_status = (latest_consent.consent_status if latest_consent else student.consent_status or "GRANTED").upper()

    if consent_status == "WITHDRAWN":
        # Look up statutory basis for retaining record despite withdrawal
        basis = (
            db.query(ProcessingBasisRecord)
            .filter(ProcessingBasisRecord.is_active == True)
            .order_by(ProcessingBasisRecord.valid_from.desc())
            .first()
        )
        legal_details = {
            "statute_reference": basis.statute_reference if basis else "AICTE Act 1987 Section 10(k)",
            "basis_type": basis.basis_type if basis else "STATUTORY_MANDATE",
            "statutory_retention_mandate": True,
        }
        return False, RETENTION_NOTICE_ON_WITHDRAWAL, legal_details

    return True, "External sharing permitted under active consent.", None


# ---------------------------------------------------------------------------
# 3. Access Events (Sensitive Data Read Logging)
# ---------------------------------------------------------------------------
def log_access_event(
    db: Session,
    actor_id: str,
    actor_role: str,
    record_type: str,
    record_id: str,
    purpose: str,
    fields_accessed: Optional[List[str]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AccessEvent:
    """
    Logs every read of a sensitive record (who, what, why/purpose, when).
    Required by DPDP compliance and audit regulations.
    """
    now = datetime.now(timezone.utc)
    evt = AccessEvent(
        actor_id=actor_id,
        actor_role=actor_role,
        record_type=record_type.strip().upper(),
        record_id=str(record_id),
        purpose=purpose.strip(),
        fields_accessed=fields_accessed or [],
        ip_address=ip_address,
        user_agent=user_agent,
        accessed_at=now,
    )
    db.add(evt)
    db.flush()
    return evt


def get_access_events(
    db: Session,
    actor_id: Optional[str] = None,
    record_type: Optional[str] = None,
    record_id: Optional[str] = None,
    purpose: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[AccessEvent]:
    """Retrieves access event audit logs (auditor/admin only)."""
    q = db.query(AccessEvent)
    if actor_id:
        q = q.filter(AccessEvent.actor_id == actor_id)
    if record_type:
        q = q.filter(AccessEvent.record_type == record_type.strip().upper())
    if record_id:
        q = q.filter(AccessEvent.record_id == str(record_id))
    if purpose:
        q = q.filter(AccessEvent.purpose.ilike(f"%{purpose.strip()}%"))

    return q.order_by(AccessEvent.accessed_at.desc()).offset(offset).limit(limit).all()
