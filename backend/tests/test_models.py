from datetime import date, datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.institution import Institution
from backend.models.user import User
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.enrollment import Enrollment
from backend.models.submission import Submission, SubmissionRow, RowOutcome
from backend.models.identity import IdentityCheck
from backend.models.validation import ValidationIssue
from backend.models.duplicate import DuplicateCandidate
from backend.models.review import ReviewCase
from backend.models.consent import ConsentRecord
from backend.models.version import RecordVersion
from backend.models.credential import Credential
from backend.models.audit import AuditEvent


def test_create_all_15_models(db_session):
    """
    Proves that all 15 SQLAlchemy models can be instantiated, persisted, and queried
    with UUID primary keys and created_at/updated_at timestamps.
    """
    now = datetime.now(timezone.utc)

    # 1. Institution
    inst = Institution(
        code="1-1002345",
        name="Indian Institute of Engineering & Technology",
        status="ACTIVE",
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    assert inst.id is not None
    assert inst.created_at is not None
    assert inst.updated_at is not None
    assert inst.code == "1-1002345"

    # 2. User
    user = User(
        email="admin@iiet.ac.in",
        password_hash="$2b$12$hashedpasswordplaceholder9999",
        role="INSTITUTION_ADMIN",
        institution_id=inst.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.id is not None
    assert user.email == "admin@iiet.ac.in"

    # 3. ProgramApproval
    approval = ProgramApproval(
        institution_id=inst.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-NORTH-2024-001",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by=user.email,
    )
    db_session.add(approval)
    db_session.commit()
    db_session.refresh(approval)
    assert approval.id is not None
    assert approval.status == ApprovalStatus.FROZEN

    # 4. SeatAllocation
    seat_alloc = SeatAllocation(
        approval_id=approval.id,
        seat_type=SeatType.REGULAR,
        approved_count=120,
        rule_version="AICTE_HANDBOOK_2024_25_V1",
    )
    db_session.add(seat_alloc)
    db_session.commit()
    db_session.refresh(seat_alloc)
    assert seat_alloc.id is not None
    assert seat_alloc.seat_type == SeatType.REGULAR
    assert seat_alloc.approved_count == 120

    # 5. Student
    student = Student(
        apaar_encrypted="enc_aes256_mock_token_abc123",
        apaar_hash="blind_index_hash_0123456789abcdef",
        apaar_masked="XXXX-XXXX-9999",
        name="Aarav Sharma",
        name_normalized="AARAV SHARMA",
        dob=date(2004, 5, 14),
        gender="MALE",
        mobile_hash="mobhash_abc",
        mobile_last4="4321",
        email_hash="emailhash_xyz",
        consent_status="GRANTED",
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    assert student.id is not None
    assert student.apaar_hash == "blind_index_hash_0123456789abcdef"

    # 6. Enrollment
    enrollment = Enrollment(
        student_id=student.id,
        institution_id=inst.id,
        approval_id=approval.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=now,
        round="1",
        status="VERIFIED",
        identity_status="PASS",
        authority_status="PASS",
        compliance_status="PASS",
        verified=True,
        version=1,
    )
    db_session.add(enrollment)
    db_session.commit()
    db_session.refresh(enrollment)
    assert enrollment.id is not None
    assert enrollment.verified is True

    # 7. Submission & SubmissionRow
    submission = Submission(
        institution_id=inst.id,
        uploaded_by=user.id,
        round="1",
        status="COMPLETED",
        idempotency_key="idemp_batch_001",
        counts={"total": 1, "valid": 1, "invalid": 0},
    )
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    assert submission.id is not None

    sub_row = SubmissionRow(
        submission_id=submission.id,
        row_number=1,
        raw={"name": "Aarav Sharma", "apaar": "123456789999"},
        normalized={"name": "AARAV SHARMA", "dob": "2004-05-14"},
        outcome=RowOutcome.COMMITTED,
        errors={},
        row_key="key_batch_001_row_1",
    )
    db_session.add(sub_row)
    db_session.commit()
    db_session.refresh(sub_row)
    assert sub_row.id is not None
    assert sub_row.outcome == RowOutcome.COMMITTED

    # 8. IdentityCheck (Rule 1: source MOCK_APAAR_V1)
    id_check = IdentityCheck(
        student_id=student.id,
        request_id="req-test-trace-01",
        source="MOCK_APAAR_V1",
        status="PASS",
        exists=True,
        name_match=True,
        dob_match=True,
        raw={"status": "SIMULATED_SUCCESS"},
    )
    db_session.add(id_check)
    db_session.commit()
    db_session.refresh(id_check)
    assert id_check.id is not None
    assert id_check.source == "MOCK_APAAR_V1"

    # 9. ValidationIssue
    issue = ValidationIssue(
        enrollment_id=enrollment.id,
        row_id=sub_row.id,
        rule_code="RULE_QUOTA_CHECK",
        severity="INFO",
        message="Quota verified within limit",
        status="RESOLVED",
    )
    db_session.add(issue)
    db_session.commit()
    db_session.refresh(issue)
    assert issue.id is not None
    assert issue.rule_code == "RULE_QUOTA_CHECK"

    # 10. DuplicateCandidate
    dup = DuplicateCandidate(
        enrollment_a=enrollment.id,
        enrollment_b=enrollment.id,
        match_type="EXACT_APAAR",
        score=1.0,
        reasons={"apaar_matched": True},
        status="DETECTED",
    )
    db_session.add(dup)
    db_session.commit()
    db_session.refresh(dup)
    assert dup.id is not None
    assert dup.match_type == "EXACT_APAAR"

    # 11. ReviewCase
    review = ReviewCase(
        type="SEAT_OVERFLOW",
        severity="MEDIUM",
        priority=50.0,
        enrollment_id=enrollment.id,
        assigned_to=user.id,
        status="OPEN",
        decision=None,
        decision_reason=None,
        evidence={"seat_limit": 120, "attempted_seat": 121},
        due_at=None,
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)
    assert review.id is not None
    assert review.priority == 50.0

    # 12. ConsentRecord
    consent = ConsentRecord(
        student_id=student.id,
        purpose="AICTE_ADMISSION_VERIFICATION",
        status="GRANTED",
        reference="CONSENT-REF-2024-001",
        timestamp=now,
    )
    db_session.add(consent)
    db_session.commit()
    db_session.refresh(consent)
    assert consent.id is not None
    assert consent.status == "GRANTED"

    # 13. RecordVersion
    version = RecordVersion(
        entity_type="ENROLLMENT",
        entity_id=enrollment.id,
        version=1,
        snapshot={"status": "VERIFIED", "seat_type": "REGULAR"},
        change_reason="Initial multi-layer verification completed",
        actor_id=user.id,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    assert version.id is not None
    assert version.version == 1

    # 14. Credential (public_ref unique)
    credential = Credential(
        enrollment_id=enrollment.id,
        public_ref="CRED-AICTE-9999-VERIFIED",
        payload={"student_name": "Aarav Sharma", "verified": True},
        signature="mock_signature_ed25519_canonical_hash",
        key_id="AICTE-KEY-2025-V1",
        expires_at=None,
        revoked_at=None,
        revoke_reason=None,
        status="ACTIVE",
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    assert credential.id is not None
    assert credential.public_ref == "CRED-AICTE-9999-VERIFIED"

    # 15. AuditEvent
    audit = AuditEvent(
        actor_id=user.id,
        action="VERIFY_ENROLLMENT",
        entity_type="ENROLLMENT",
        entity_id=enrollment.id,
        reason="Passed L1, L2, and L3 verification layers",
        request_id="req-test-trace-01",
        prev_hash=None,
        hash="sha256_hash_root_event",
    )
    db_session.add(audit)
    db_session.commit()
    db_session.refresh(audit)
    assert audit.id is not None
    assert audit.action == "VERIFY_ENROLLMENT"


def test_unique_submission_id_and_row_number_enforced(db_session):
    """Enforce at DB level: unique (submission_id, row_number)."""
    inst = Institution(code="1-99901", name="Test Inst", status="ACTIVE")
    user = User(email="test@inst.edu", password_hash="hash", role="INSTITUTION_ADMIN")
    db_session.add_all([inst, user])
    db_session.commit()

    sub = Submission(institution_id=inst.id, uploaded_by=user.id, round="1", status="PENDING")
    db_session.add(sub)
    db_session.commit()

    row1 = SubmissionRow(
        submission_id=sub.id,
        row_number=1,
        raw={"test": 1},
        row_key="key_uniq_1",
    )
    db_session.add(row1)
    db_session.commit()

    # Attempt inserting duplicate (submission_id, row_number)
    row2 = SubmissionRow(
        submission_id=sub.id,
        row_number=1,
        raw={"test": 2},
        row_key="key_uniq_2",
    )
    db_session.add(row2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_row_key_enforced(db_session):
    """Enforce at DB level: unique row_key."""
    inst = Institution(code="1-99902", name="Test Inst 2", status="ACTIVE")
    user = User(email="test2@inst.edu", password_hash="hash", role="INSTITUTION_ADMIN")
    db_session.add_all([inst, user])
    db_session.commit()

    sub = Submission(institution_id=inst.id, uploaded_by=user.id, round="1", status="PENDING")
    db_session.add(sub)
    db_session.commit()

    row1 = SubmissionRow(
        submission_id=sub.id,
        row_number=1,
        raw={"test": 1},
        row_key="identical_row_key_xyz",
    )
    db_session.add(row1)
    db_session.commit()

    # Attempt inserting duplicate row_key even with different row_number
    row2 = SubmissionRow(
        submission_id=sub.id,
        row_number=2,
        raw={"test": 2},
        row_key="identical_row_key_xyz",
    )
    db_session.add(row2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_public_ref_enforced(db_session):
    """Enforce at DB level: public_ref unique."""
    inst = Institution(code="1-99903", name="Test Inst 3", status="ACTIVE")
    student1 = Student(
        apaar_encrypted="enc1", apaar_hash="hash1", apaar_masked="M1",
        name="S1", name_normalized="S1", dob=date(2000, 1, 1), gender="MALE"
    )
    student2 = Student(
        apaar_encrypted="enc2", apaar_hash="hash2", apaar_masked="M2",
        name="S2", name_normalized="S2", dob=date(2000, 1, 1), gender="FEMALE"
    )
    db_session.add_all([inst, student1, student2])
    db_session.commit()

    approval = ProgramApproval(
        institution_id=inst.id, programme="ENG", branch="CSE", academic_year="2024-2025",
        approval_ref="REF1", status=ApprovalStatus.FROZEN
    )
    db_session.add(approval)
    db_session.commit()

    now = datetime.now(timezone.utc)
    enrollment1 = Enrollment(
        student_id=student1.id, institution_id=inst.id, approval_id=approval.id,
        academic_year="2024-2025", seat_type="REGULAR", category="OPEN", admission_date=now
    )
    enrollment2 = Enrollment(
        student_id=student2.id, institution_id=inst.id, approval_id=approval.id,
        academic_year="2024-2025", seat_type="REGULAR", category="OPEN", admission_date=now
    )
    db_session.add_all([enrollment1, enrollment2])
    db_session.commit()

    cred1 = Credential(
        enrollment_id=enrollment1.id,
        public_ref="SAME_PUBLIC_REF_999",
        payload={"claim": "ok"},
        signature="sig1",
    )
    db_session.add(cred1)
    db_session.commit()

    cred2 = Credential(
        enrollment_id=enrollment2.id,
        public_ref="SAME_PUBLIC_REF_999",
        payload={"claim": "duplicate"},
        signature="sig2",
    )
    db_session.add(cred2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
