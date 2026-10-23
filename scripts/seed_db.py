"""
Database Seeding Script for APAAR Connect
Generates synthetic data conforming to Rules 1-12:
- Rule 1: Labeled MOCK_APAAR_V1
- Rule 2: Synthetic data
- Rule 3: Per-category seat quota compliance
- Rule 10: AES-256-GCM encrypted APAAR IDs with keyed blind index
"""
import os
import sys
from datetime import date, datetime, timezone

# Ensure project paths on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from backend.database import SessionLocal, Base, engine
from backend.models import (
    Institution,
    User,
    ProgramApproval,
    ApprovalStatus,
    SeatAllocation,
    SeatType,
    Student,
    Enrollment,
    Submission,
    SubmissionRow,
    RowOutcome,
    IdentityCheck,
    ValidationIssue,
    DuplicateCandidate,
    ReviewCase,
    ConsentRecord,
    RecordVersion,
    Credential,
    AuditEvent,
)
from backend.security.crypto import encrypt_apaar, compute_apaar_hash, mask_apaar, hash_password
from backend.services.audit import record_audit_event
from backend.services.credential import issue_verifiable_credential


def seed_database():
    print("[Seed] Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Check if already seeded
        if db.query(Institution).filter(Institution.code == "1-1001").first():
            print("[Seed] Database already seeded. Skipping.")
            return

        now = datetime.now(timezone.utc)

        print("[Seed] Creating institutions...")
        iit_delhi = Institution(
            code="1-1001",
            name="Indian Institute of Technology Delhi",
            status="ACTIVE",
        )
        nit_trichy = Institution(
            code="1-1002",
            name="National Institute of Technology Tiruchirappalli",
            status="ACTIVE",
        )
        db.add_all([iit_delhi, nit_trichy])
        db.flush()

        print("[Seed] Creating 7 demo users (one per role, two institutions)...")
        demo_password = hash_password("Password123!")

        # 1. AICTE_ADMIN (Central Authority)
        user_aicte_admin = User(
            email="admin@aicte.gov.in",
            password_hash=demo_password,
            role="AICTE_ADMIN",
            institution_id=None,
            is_active=True,
        )
        # 2. AICTE_REVIEWER (Adjudicates duplicate/quota exceptions)
        user_aicte_reviewer = User(
            email="reviewer@aicte.gov.in",
            password_hash=demo_password,
            role="AICTE_REVIEWER",
            institution_id=None,
            is_active=True,
        )
        # 3. INSTITUTION_ADMIN (Institution A: IIT Delhi)
        user_inst_admin_a = User(
            email="admin.iitd@iitd.ac.in",
            password_hash=demo_password,
            role="INSTITUTION_ADMIN",
            institution_id=iit_delhi.id,
            is_active=True,
        )
        # 4. INSTITUTION_OPERATOR (Institution A: IIT Delhi)
        user_inst_op_a = User(
            email="operator.iitd@iitd.ac.in",
            password_hash=demo_password,
            role="INSTITUTION_OPERATOR",
            institution_id=iit_delhi.id,
            is_active=True,
        )
        # 5. INSTITUTION_OPERATOR (Institution B: NIT Trichy)
        user_inst_op_b = User(
            email="operator.nitt@nitt.edu",
            password_hash=demo_password,
            role="INSTITUTION_OPERATOR",
            institution_id=nit_trichy.id,
            is_active=True,
        )
        # 6. STUDENT (Enrolled Student at IIT Delhi)
        user_student = User(
            email="student.priya@student.gov.in",
            password_hash=demo_password,
            role="STUDENT",
            institution_id=iit_delhi.id,
            is_active=True,
        )
        # 7. AUDITOR (Central Comptroller & Auditor General)
        user_auditor = User(
            email="auditor@cag.gov.in",
            password_hash=demo_password,
            role="AUDITOR",
            institution_id=None,
            is_active=True,
        )

        db.add_all([
            user_aicte_admin,
            user_aicte_reviewer,
            user_inst_admin_a,
            user_inst_op_a,
            user_inst_op_b,
            user_student,
            user_auditor,
        ])
        db.flush()

        print("[Seed] Creating program approvals and frozen seat allocations...")
        approval_cse = ProgramApproval(
            institution_id=iit_delhi.id,
            programme="ENGINEERING_AND_TECHNOLOGY",
            branch="COMPUTER_SCIENCE_AND_ENGINEERING",
            campus="MAIN",
            shift="FIRST",
            academic_year="2024-2025",
            approval_ref="EOA-NORTH-2024-IITD-CSE",
            version=1,
            status=ApprovalStatus.FROZEN,
            frozen_at=now,
            frozen_by=user_aicte_admin.email,
        )
        db.add(approval_cse)
        db.flush()

        alloc_regular = SeatAllocation(
            approval_id=approval_cse.id,
            seat_type=SeatType.REGULAR,
            approved_count=120,
            rule_version="AICTE_HANDBOOK_2024_25_V1",
        )
        alloc_nri = SeatAllocation(
            approval_id=approval_cse.id,
            seat_type=SeatType.NRI,
            approved_count=15,
            rule_version="AICTE_HANDBOOK_2024_25_V1",
        )
        db.add_all([alloc_regular, alloc_nri])
        db.flush()

        print("[Seed] Creating synthetic students and enrollments...")
        raw_apaar_1 = "987654321012"
        student_1 = Student(
            apaar_encrypted=encrypt_apaar(raw_apaar_1),
            apaar_hash=compute_apaar_hash(raw_apaar_1),
            apaar_masked=mask_apaar(raw_apaar_1),
            name="Priya Patel",
            name_normalized="PRIYA PATEL",
            dob=date(2005, 3, 21),
            gender="FEMALE",
            mobile_hash="mock_hash_9876543210",
            mobile_last4="3210",
            email_hash="mock_hash_priya_patel",
            consent_status="GRANTED",
        )
        db.add(student_1)
        db.flush()

        # Consent record
        consent_1 = ConsentRecord(
            student_id=student_1.id,
            purpose="AICTE_ADMISSION_VERIFICATION",
            consent_status="GRANTED",
            status="GRANTED",
            reference="CONSENT-2024-IITD-001",
            timestamp=now,
        )
        db.add(consent_1)

        # L1 Identity check
        id_check_1 = IdentityCheck(
            student_id=student_1.id,
            request_id="req-seed-001",
            source="MOCK_APAAR_V1",
            status="PASS",
            exists=True,
            name_match=True,
            dob_match=True,
            raw={"simulated": True, "source": "MOCK_APAAR_V1"},
        )
        db.add(id_check_1)

        # Enrollment passing all 3 layers -> Verified and CONFIRMED
        enrollment_1 = Enrollment(
            student_id=student_1.id,
            institution_id=iit_delhi.id,
            approval_id=approval_cse.id,
            academic_year="2024-2025",
            seat_type="REGULAR",
            category="OPEN",
            admission_date=now,
            round="1",
            status="CONFIRMED",
            identity_status="PASS",
            authority_status="PASS",
            compliance_status="PASS",
            verified=True,
            version=1,
        )
        db.add(enrollment_1)
        db.flush()

        # Verifiable Credential for verified student
        cred_1 = issue_verifiable_credential(db, enrollment_1)

        # Record audit event
        record_audit_event(
            db=db,
            actor_id=user_aicte_admin.id,
            action="SEED_INITIAL_VERIFIED_ENROLLMENT",
            entity_type="ENROLLMENT",
            entity_id=enrollment_1.id,
            reason="Seed synthetic verified student enrollment with signed credential",
            request_id="req-seed-001",
        )

        db.commit()
        print("[Seed] Successfully populated synthetic database with test entities!")

    except Exception as e:
        db.rollback()
        print(f"[Seed] Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
