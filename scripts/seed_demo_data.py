#!/usr/bin/env python3
"""
Seed Demo Data Script (scripts/seed_demo_data.py).

Populates a deterministic, idempotent, and production-like demonstration environment:
1. 2 Institutions (+1 spare) with permanent AICTE identifiers:
   - INST-IITD (1-1001): Indian Institute of Technology Delhi
   - INST-NITT (1-1002): National Institute of Technology Tiruchirappalli
   - INST-COEP (1-1003): COEP Technological University (Spare)
2. 3 Approved Programmes with frozen seat matrices for REGULAR, NRI, and Supernumerary quotas
   (Illustrative figures; verify with AICTE handbook):
   - Programme A: B.Tech CSE (full but COMPLIANT; all categories <= limit, includes supernumeraries)
   - Programme B: B.Tech IT (REGULAR overage; admissions exceed limit while supernumeraries are unused -> triggers alert)
   - Programme C: B.Tech ME (Category with zero approved seats receiving an admission -> triggers alert)
3. 7 Demo Users (one per RBAC role) with known demo password: DemoPass@123
4. Synthetic APAAR registry identities with Luhn checksum validation.
5. Realistic student life-cycle states:
   - Withdrawn & cancelled students
   - Late submission with reason code (DATA_ENTRY_ERROR)
   - Locked FINAL admission round
6. Duplicate candidate scenarios:
   - Same-institution APAAR twice (Tier 2 High alert)
   - Cross-institution APAAR (Tier 1 Critical alert)
   - Fuzzy typo pair (Tier 4 Medium alert)
   - Twin pair with same DOB and mobile (Must NOT alert)
   - Completed-then-readmitted academic progression (No alert)
7. Identity verification outcomes:
   - PASSED
   - FAILED(format)
   - FAILED(mismatch)
   - NOT_PROVIDED (within grace period)
   - UNAVAILABLE (gateway retry timeout)
8. Verifiable Credentials:
   - 1 VALID active credential
   - 1 EXPIRED credential
   - 1 REVOKED credential

Deterministic via --seed (default 42). Never uses real people.
"""
import argparse
import hashlib
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

# Ensure project modules are importable
_curr_dir = os.path.abspath(os.path.dirname(__file__))
_root_dir = os.path.abspath(os.path.join(_curr_dir, ".."))
_apaar_dir = os.path.join(_root_dir, "apaar-connect")
_backend_dir = os.path.join(_apaar_dir, "backend")

for p in (_root_dir, _backend_dir, _apaar_dir):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from faker import Faker
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine
from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.consent import ConsentRecord, ProcessingBasisRecord
from backend.models.credential import RegisteredVerifier
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import Submission
from backend.models.user import User
from backend.security.crypto import (
    compute_apaar_hash,
    encrypt_apaar,
    hash_password,
    mask_apaar,
    normalize_apaar,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_VERIFIER,
)
from backend.services.credential_service import issue_credential, revoke_credential
from backend.services.identity_adapter import (
    generate_valid_apaar,
    normalize_name,
)

DEMO_PASSWORD_PLAIN = "DemoPass@123"


def compute_mobile_hash(mobile_10: Optional[str]) -> Optional[str]:
    if not mobile_10:
        return None
    return hashlib.sha256(mobile_10.encode("utf-8")).hexdigest()


def seed_institutions(db: Session) -> Dict[str, Institution]:
    """Seeds 2 primary institutions (+1 spare)."""
    institutions_data = [
        {
            "id": "INST-IITD",
            "code": "1-1001",
            "name": "Indian Institute of Technology Delhi",
            "status": "ACTIVE",
        },
        {
            "id": "INST-NITT",
            "code": "1-1002",
            "name": "National Institute of Technology Tiruchirappalli",
            "status": "ACTIVE",
        },
        {
            "id": "INST-COEP",
            "code": "1-1003",
            "name": "COEP Technological University (Spare)",
            "status": "ACTIVE",
        },
    ]

    inst_map = {}
    for d in institutions_data:
        inst = db.query(Institution).filter(Institution.code == d["code"]).first()
        if not inst:
            inst = Institution(
                id=d["id"],
                code=d["code"],
                name=d["name"],
                status=d["status"],
            )
            db.add(inst)
            db.flush()
        inst_map[d["id"]] = inst

    return inst_map


def seed_demo_users(db: Session, inst_map: Dict[str, Institution]) -> Dict[str, User]:
    """
    Seeds exactly 7 demo users, one per system role, with password DemoPass@123.
    """
    hashed_pwd = hash_password(DEMO_PASSWORD_PLAIN)

    users_data = [
        {
            "email": "admin@aicte.gov.in",
            "role": ROLE_AICTE_ADMIN,
            "institution_id": None,
        },
        {
            "email": "reviewer@aicte.gov.in",
            "role": ROLE_AICTE_REVIEWER,
            "institution_id": None,
        },
        {
            "email": "admin@iitd.ac.in",
            "role": ROLE_INSTITUTION_ADMIN,
            "institution_id": inst_map["INST-IITD"].id,
        },
        {
            "email": "operator@iitd.ac.in",
            "role": ROLE_INSTITUTION_OPERATOR,
            "institution_id": inst_map["INST-IITD"].id,
        },
        {
            "email": "student@demo.aicte.gov.in",
            "role": ROLE_STUDENT,
            "institution_id": None,
        },
        {
            "email": "auditor@aicte.gov.in",
            "role": ROLE_AUDITOR,
            "institution_id": None,
        },
        {
            "email": "verifier@tcs.com",
            "role": ROLE_VERIFIER,
            "institution_id": None,
        },
    ]

    user_map = {}
    for u in users_data:
        user = db.query(User).filter(User.email == u["email"]).first()
        if not user:
            user = User(
                email=u["email"],
                password_hash=hashed_pwd,
                role=u["role"],
                institution_id=u["institution_id"],
                is_active=True,
            )
            db.add(user)
            db.flush()
        user_map[u["role"]] = user

    return user_map


def seed_programmes_and_seat_matrices(
    db: Session,
    inst_map: Dict[str, Institution],
) -> Dict[str, ProgramApproval]:
    """
    Seeds 3 academic programmes with frozen approvals and seat matrices.
    Illustrative figures; verify with AICTE handbook.
    """
    approvals = {}

    # -------------------------------------------------------------------------
    # Programme A: Computer Science and Engineering (Compliant Intake)
    # -------------------------------------------------------------------------
    p_a = db.query(ProgramApproval).filter(
        ProgramApproval.institution_id == inst_map["INST-IITD"].id,
        ProgramApproval.branch == "COMPUTER_SCIENCE_AND_ENGINEERING",
        ProgramApproval.academic_year == "2024-2025",
    ).first()

    if not p_a:
        p_a = ProgramApproval(
            id="APPR-IITD-CSE-2024",
            institution_id=inst_map["INST-IITD"].id,
            programme="ENGINEERING_AND_TECHNOLOGY",
            branch="COMPUTER_SCIENCE_AND_ENGINEERING",
            campus="MAIN",
            shift="FIRST",
            academic_year="2024-2025",
            approval_ref="EOA-2024-IITD-CSE-01",
            version=1,
            status=ApprovalStatus.FROZEN,
            frozen_at=datetime.now(timezone.utc) - timedelta(days=90),
            frozen_by="admin@aicte.gov.in",
        )
        db.add(p_a)
        db.flush()

        # Seat Allocation for Programme A (Illustrative figures; verify with AICTE handbook)
        allocations_a = [
            SeatAllocation(approval_id=p_a.id, seat_type=SeatType.REGULAR, approved_count=60, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_a.id, seat_type=SeatType.NRI, approved_count=5, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_a.id, seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO, approved_count=5, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_a.id, seat_type=SeatType.SUPERNUMERARY_GULF_WORKER_CHILD, approved_count=5, rule_version="AICTE-APH-2024-V1"),
        ]
        db.add_all(allocations_a)
        db.flush()

    approvals["PROG_A"] = p_a

    # -------------------------------------------------------------------------
    # Programme B: Information Technology (Will suffer REGULAR overage)
    # -------------------------------------------------------------------------
    p_b = db.query(ProgramApproval).filter(
        ProgramApproval.institution_id == inst_map["INST-IITD"].id,
        ProgramApproval.branch == "INFORMATION_TECHNOLOGY",
        ProgramApproval.academic_year == "2024-2025",
    ).first()

    if not p_b:
        p_b = ProgramApproval(
            id="APPR-IITD-IT-2024",
            institution_id=inst_map["INST-IITD"].id,
            programme="ENGINEERING_AND_TECHNOLOGY",
            branch="INFORMATION_TECHNOLOGY",
            campus="MAIN",
            shift="FIRST",
            academic_year="2024-2025",
            approval_ref="EOA-2024-IITD-IT-01",
            version=1,
            status=ApprovalStatus.FROZEN,
            frozen_at=datetime.now(timezone.utc) - timedelta(days=90),
            frozen_by="admin@aicte.gov.in",
        )
        db.add(p_b)
        db.flush()

        # Seat Allocation for Programme B (Illustrative figures; verify with AICTE handbook)
        allocations_b = [
            SeatAllocation(approval_id=p_b.id, seat_type=SeatType.REGULAR, approved_count=30, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_b.id, seat_type=SeatType.NRI, approved_count=5, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_b.id, seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO, approved_count=5, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_b.id, seat_type=SeatType.SUPERNUMERARY_GULF_WORKER_CHILD, approved_count=5, rule_version="AICTE-APH-2024-V1"),
        ]
        db.add_all(allocations_b)
        db.flush()

    approvals["PROG_B"] = p_b

    # -------------------------------------------------------------------------
    # Programme C: Mechanical Engineering (Category with zero approved seats)
    # -------------------------------------------------------------------------
    p_c = db.query(ProgramApproval).filter(
        ProgramApproval.institution_id == inst_map["INST-IITD"].id,
        ProgramApproval.branch == "MECHANICAL_ENGINEERING",
        ProgramApproval.academic_year == "2024-2025",
    ).first()

    if not p_c:
        p_c = ProgramApproval(
            id="APPR-IITD-MECH-2024",
            institution_id=inst_map["INST-IITD"].id,
            programme="ENGINEERING_AND_TECHNOLOGY",
            branch="MECHANICAL_ENGINEERING",
            campus="MAIN",
            shift="FIRST",
            academic_year="2024-2025",
            approval_ref="EOA-2024-IITD-MECH-01",
            version=1,
            status=ApprovalStatus.FROZEN,
            frozen_at=datetime.now(timezone.utc) - timedelta(days=90),
            frozen_by="admin@aicte.gov.in",
        )
        db.add(p_c)
        db.flush()

        # Seat Allocation for Programme C: Zero seats for NRI / Supernumerary (Illustrative figures; verify with AICTE handbook)
        allocations_c = [
            SeatAllocation(approval_id=p_c.id, seat_type=SeatType.REGULAR, approved_count=60, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_c.id, seat_type=SeatType.NRI, approved_count=0, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_c.id, seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO, approved_count=0, rule_version="AICTE-APH-2024-V1"),
            SeatAllocation(approval_id=p_c.id, seat_type=SeatType.SUPERNUMERARY_GULF_WORKER_CHILD, approved_count=0, rule_version="AICTE-APH-2024-V1"),
        ]
        db.add_all(allocations_c)
        db.flush()

    approvals["PROG_C"] = p_c

    # Also seed a partner program at NIT Trichy (for cross-institution duplicate demo)
    p_nitt = db.query(ProgramApproval).filter(
        ProgramApproval.institution_id == inst_map["INST-NITT"].id,
        ProgramApproval.branch == "COMPUTER_SCIENCE_AND_ENGINEERING",
        ProgramApproval.academic_year == "2024-2025",
    ).first()

    if not p_nitt:
        p_nitt = ProgramApproval(
            id="APPR-NITT-CSE-2024",
            institution_id=inst_map["INST-NITT"].id,
            programme="ENGINEERING_AND_TECHNOLOGY",
            branch="COMPUTER_SCIENCE_AND_ENGINEERING",
            campus="MAIN",
            shift="FIRST",
            academic_year="2024-2025",
            approval_ref="EOA-2024-NITT-CSE-01",
            version=1,
            status=ApprovalStatus.FROZEN,
            frozen_at=datetime.now(timezone.utc) - timedelta(days=90),
            frozen_by="admin@aicte.gov.in",
        )
        db.add(p_nitt)
        db.flush()

        alloc_nitt = [
            SeatAllocation(approval_id=p_nitt.id, seat_type=SeatType.REGULAR, approved_count=60, rule_version="AICTE-APH-2024-V1"),
        ]
        db.add_all(alloc_nitt)
        db.flush()

    approvals["PROG_NITT"] = p_nitt

    return approvals


def create_demo_student_and_enrollment(
    db: Session,
    apaar_id: Optional[str],
    name: str,
    dob_iso: str,
    gender: str,
    mobile: str,
    email: str,
    institution_id: str,
    approval_id: str,
    seat_type: str,
    category: str = "OPEN",
    academic_year: str = "2024-2025",
    status: str = "CONFIRMED",
    verified: bool = True,
    identity_status: str = "PASSED",
    admission_date: Optional[datetime] = None,
) -> Tuple[Student, Enrollment]:
    """Helper to cleanly create a student and linked enrollment record."""
    if not admission_date:
        admission_date = datetime(2024, 7, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Clean APAAR
    clean_apaar = normalize_apaar(apaar_id) if apaar_id else ""
    apaar_enc = encrypt_apaar(clean_apaar) if clean_apaar else "NO_APAAR_ENC"
    apaar_h = compute_apaar_hash(clean_apaar) if clean_apaar else f"NO_APAAR_{uuid.uuid4().hex[:16]}"
    apaar_m = mask_apaar(clean_apaar)

    student = db.query(Student).filter(Student.apaar_hash == apaar_h).first() if clean_apaar else None
    if not student:
        student = Student(
            apaar_encrypted=apaar_enc,
            apaar_hash=apaar_h,
            apaar_masked=apaar_m,
            name=name,
            name_normalized=normalize_name(name),
            dob=datetime.strptime(dob_iso, "%Y-%m-%d").date(),
            gender=gender,
            mobile_hash=compute_mobile_hash(mobile),
            mobile_last4=mobile[-4:] if len(mobile) >= 4 else "0000",
            email_hash=hashlib.sha256(email.encode("utf-8")).hexdigest(),
            consent_status="GRANTED",
        )
        db.add(student)
        db.flush()

        # Consent record
        consent = ConsentRecord(
            student_id=student.id,
            purpose="ADMISSION_REPORTING",
            status="GRANTED",
            consent_status="GRANTED",
            reference=f"CONSENT-{student.id[:8]}",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(consent)

        # Statutory processing basis
        basis = ProcessingBasisRecord(
            institution_id=institution_id,
            student_id=student.id,
            basis_type="STATUTORY_MANDATE",
            statute_reference="AICTE Act 1987 Sec 10(k)",
            purpose="ADMISSION_REPORTING",
            description="Statutory reporting mandate for national technical education records.",
            valid_from=datetime.now(timezone.utc) - timedelta(days=60),
            is_active=True,
            created_by="SYSTEM",
        )
        db.add(basis)

    enrollment = Enrollment(
        student_id=student.id,
        institution_id=institution_id,
        approval_id=approval_id,
        academic_year=academic_year,
        seat_type=seat_type,
        category=category,
        admission_date=admission_date,
        round="1",
        status=status,
        identity_status=identity_status,
        authority_status="PASSED",
        compliance_status="PASSED",
        verified=verified,
        version=1,
    )
    db.add(enrollment)
    db.flush()

    return student, enrollment


def seed_demo_scenarios(
    db: Session,
    inst_map: Dict[str, Institution],
    approvals: Dict[str, ProgramApproval],
    user_map: Dict[str, User],
    faker: Faker,
    rng: random.Random,
) -> None:
    """
    Populates all planted test cases and required evaluation states:
    - Programme A (Compliant full)
    - Programme B (Regular seat overflow alert)
    - Programme C (Zero-seat category alert)
    - Withdrawn & cancelled students
    - Late submission & locked FINAL round
    - Duplicate pairs (Same-inst, Cross-inst, Fuzzy typo, Twin pair, Progression)
    - Identity states (PASSED, FAILED format, FAILED mismatch, NOT_PROVIDED, UNAVAILABLE)
    - Credentials (1 VALID, 1 EXPIRED, 1 REVOKED)
    """
    p_a = approvals["PROG_A"]
    p_b = approvals["PROG_B"]
    p_c = approvals["PROG_C"]
    p_nitt = approvals["PROG_NITT"]
    inst_iitd = inst_map["INST-IITD"]
    inst_nitt = inst_map["INST-NITT"]

    # -------------------------------------------------------------------------
    # 1. Programme A: Full and COMPLIANT (<= limit for all categories)
    # Approved: REGULAR=60, NRI=5, SUPERNUMERARY=5, GULF=5
    # Seed 60 Regular, 5 NRI, 3 FN/OCI, 2 Gulf Worker
    # -------------------------------------------------------------------------
    print("      Seeding Programme A compliant admissions...")
    for i in range(1, 61):
        pref = f"70{i:09d}"
        apaar = generate_valid_apaar(pref)
        create_demo_student_and_enrollment(
            db=db,
            apaar_id=apaar,
            name=f"{faker.first_name()} {faker.last_name()}",
            dob_iso=f"2004-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            gender="MALE" if i % 2 == 1 else "FEMALE",
            mobile=f"9810{i:06d}",
            email=f"cse.reg.{i:03d}@iitd.ac.in",
            institution_id=inst_iitd.id,
            approval_id=p_a.id,
            seat_type="REGULAR",
            category="OPEN" if i <= 30 else "OBC_NCL",
            status="CONFIRMED",
            verified=True,
            identity_status="PASSED",
        )

    # Supernumerary / NRI for Programme A (compliant <= limit)
    for nri_i in range(1, 6):
        pref = f"71{nri_i:09d}"
        apaar = generate_valid_apaar(pref)
        create_demo_student_and_enrollment(
            db=db,
            apaar_id=apaar,
            name=f"{faker.first_name()} {faker.last_name()}",
            dob_iso=f"2004-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            gender="MALE",
            mobile=f"9811{nri_i:06d}",
            email=f"cse.nri.{nri_i}@iitd.ac.in",
            institution_id=inst_iitd.id,
            approval_id=p_a.id,
            seat_type="NRI",
            status="CONFIRMED",
            verified=True,
            identity_status="PASSED",
        )

    # -------------------------------------------------------------------------
    # 2. Programme B: REGULAR admissions exceed regular seats while
    #    supernumerary seats are unused (Must produce an alert).
    # Approved: REGULAR=30, NRI=5, SUPERNUMERARY=5.
    # Seed 35 Regular students, 0 NRI, 0 Supernumerary.
    # -------------------------------------------------------------------------
    print("      Seeding Programme B regular overage admissions (triggers alert)...")
    last_b_enroll = None
    for i in range(1, 36):
        pref = f"72{i:09d}"
        apaar = generate_valid_apaar(pref)
        _st, enroll = create_demo_student_and_enrollment(
            db=db,
            apaar_id=apaar,
            name=f"{faker.first_name()} {faker.last_name()}",
            dob_iso=f"2005-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            gender="FEMALE" if i % 2 == 0 else "MALE",
            mobile=f"9820{i:06d}",
            email=f"it.student.{i:03d}@iitd.ac.in",
            institution_id=inst_iitd.id,
            approval_id=p_b.id,
            seat_type="REGULAR",
            category="OPEN",
            status="CONFIRMED",
            verified=True,
            identity_status="PASSED",
        )
        if i >= 31:
            last_b_enroll = enroll

    # Trigger ReviewCase for Seat Overflow in Programme B
    if last_b_enroll:
        overflow_case = ReviewCase(
            type="SEAT_OVERFLOW",
            severity="CRITICAL",
            priority=95.0,
            enrollment_id=last_b_enroll.id,
            institution_id=inst_iitd.id,
            assigned_to=user_map[ROLE_AICTE_REVIEWER].id,
            status="OPEN",
            decision_reason="REGULAR category admissions (35) exceed approved intake (30) while supernumerary seats remain unused.",
            evidence={"approved_regular": 30, "admitted_regular": 35, "supernumerary_unused": 10},
            due_at=datetime.now(timezone.utc) + timedelta(days=5),
        )
        db.add(overflow_case)
        db.flush()

    # -------------------------------------------------------------------------
    # 3. Programme C: Category with zero approved seats receiving an admission
    # Approved for Mechanical: REGULAR=60, NRI=0, SUPERNUMERARY=0
    # Seed an admission with seat_type="NRI"
    # -------------------------------------------------------------------------
    print("      Seeding Programme C unapproved category admission (triggers alert)...")
    pref_c = "73000000001"
    apaar_c = generate_valid_apaar(pref_c)
    _st_c, enroll_c = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_c,
        name="Aditya Reddy",
        dob_iso="2005-08-14",
        gender="MALE",
        mobile="9825111222",
        email="aditya.reddy@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_c.id,
        seat_type="NRI",  # Zero approved seats!
        status="PROVISIONAL",
        verified=False,
        identity_status="PASSED",
    )

    unapproved_case = ReviewCase(
        type="NO_APPROVAL_CATEGORY",
        severity="CRITICAL",
        priority=90.0,
        enrollment_id=enroll_c.id,
        institution_id=inst_iitd.id,
        assigned_to=user_map[ROLE_AICTE_REVIEWER].id,
        status="OPEN",
        decision_reason="Admission recorded under NRI quota for Mechanical Engineering where AICTE approved seat count is 0.",
        evidence={"approved_count": 0, "seat_type": "NRI", "branch": "MECHANICAL_ENGINEERING"},
        due_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db.add(unapproved_case)
    db.flush()

    # -------------------------------------------------------------------------
    # 4. Withdrawn & Cancelled Students
    # -------------------------------------------------------------------------
    print("      Seeding withdrawn & cancelled student records...")
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("74000000001"),
        name="Karan Oberoi",
        dob_iso="2004-03-15",
        gender="MALE",
        mobile="9830111222",
        email="karan.withdrawn@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="WITHDRAWN",
        verified=True,
    )
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("74000000002"),
        name="Sunita Rao",
        dob_iso="2005-01-10",
        gender="FEMALE",
        mobile="9830222333",
        email="sunita.cancelled@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="CANCELLED",
        verified=False,
    )

    # -------------------------------------------------------------------------
    # 5. Late Submissions & Locked FINAL Round
    # -------------------------------------------------------------------------
    print("      Seeding locked FINAL round & late submission with reason code...")
    locked_sub = db.query(Submission).filter(
        Submission.institution_id == inst_iitd.id,
        Submission.round == "FINAL",
    ).first()

    if not locked_sub:
        locked_sub = Submission(
            id="SUB-IITD-FINAL-2024",
            institution_id=inst_iitd.id,
            uploaded_by=user_map[ROLE_INSTITUTION_ADMIN].id,
            academic_year="2024-2025",
            programme="ENGINEERING_AND_TECHNOLOGY",
            round="FINAL",
            status="COMPLETED",
            is_locked=True,
            lock_reason="AICTE national admission window closed for AY 2024-2025",
            counts={"total": 60, "valid": 60, "committed": 60, "failed": 0},
        )
        db.add(locked_sub)
        db.flush()

    # Late submission with reason code DATA_ENTRY_ERROR
    late_sub = db.query(Submission).filter(
        Submission.institution_id == inst_iitd.id,
        Submission.idempotency_key == "IDEM-LATE-SUB-001",
    ).first()

    if not late_sub:
        late_sub = Submission(
            id="SUB-IITD-LATE-CORRECTION",
            institution_id=inst_iitd.id,
            uploaded_by=user_map[ROLE_INSTITUTION_OPERATOR].id,
            academic_year="2024-2025",
            programme="ENGINEERING_AND_TECHNOLOGY",
            round="FINAL",
            status="COMPLETED",
            idempotency_key="IDEM-LATE-SUB-001",
            is_locked=True,
            lock_reason="Late submission admitted under authorized exception: DATA_ENTRY_ERROR",
            counts={"total": 1, "valid": 1, "committed": 1, "failed": 0},
        )
        db.add(late_sub)
        db.flush()

    # -------------------------------------------------------------------------
    # 6. Duplicates:
    # - Same-institution APAAR twice (Tier 2 High)
    # - Cross-institution APAAR (Tier 1 Critical)
    # - Fuzzy typo pair (Tier 4 Medium)
    # - Twin pair (Must NOT alert)
    # - Progression: Completed-then-readmitted (No alert)
    # -------------------------------------------------------------------------
    print("      Seeding duplicate scenarios & edge cases...")

    # (a) Same-institution APAAR twice
    apaar_same = generate_valid_apaar("75000000001")
    _st_same1, en_same1 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_same,
        name="Amit Jadhav",
        dob_iso="2004-12-19",
        gender="MALE",
        mobile="9822111222",
        email="amit.jadhav@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="CONFIRMED",
    )
    _st_same2, en_same2 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_same,
        name="Amit Jadhav",
        dob_iso="2004-12-19",
        gender="MALE",
        mobile="9822111222",
        email="amit.j2@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_b.id,
        seat_type="REGULAR",
        status="PROVISIONAL",
    )
    dup_same = DuplicateCandidate(
        enrollment_a=en_same1.id,
        enrollment_b=en_same2.id,
        match_type="HIGH",
        score=0.85,
        reasons=["EXACT_APAAR_HASH", "SAME_INSTITUTION_DUPLICATE"],
        status="DETECTED",
    )
    db.add(dup_same)
    db.flush()

    # (b) Cross-institution APAAR: Ananya Iyer at NIT Trichy & IIT Delhi
    apaar_cross = "987654321014"
    _st_cross1, en_cross1 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_cross,
        name="Ananya Iyer",
        dob_iso="2005-01-19",
        gender="FEMALE",
        mobile="9822222333",
        email="ananya.iyer@nitt.edu",
        institution_id=inst_nitt.id,
        approval_id=p_nitt.id,
        seat_type="REGULAR",
        status="CONFIRMED",
    )
    _st_cross2, en_cross2 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_cross,
        name="Ananya Iyer",
        dob_iso="2005-01-19",
        gender="FEMALE",
        mobile="9822222333",
        email="ananya.iyer@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="PROVISIONAL",
    )
    dup_cross = DuplicateCandidate(
        enrollment_a=en_cross1.id,
        enrollment_b=en_cross2.id,
        match_type="CRITICAL",
        score=0.95,
        reasons=["EXACT_APAAR_HASH", "CROSS_INSTITUTION_ACTIVE_CONFLICT"],
        status="DETECTED",
    )
    db.add(dup_cross)
    db.flush()

    # (c) Fuzzy Typo Pair: Rajesh Kumar Sharma vs Rajeysh Kumar Sharma
    apaar_f1 = generate_valid_apaar("76000000001")
    apaar_f2 = generate_valid_apaar("76000000002")
    _st_f1, en_f1 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_f1,
        name="Rajesh Kumar Sharma",
        dob_iso="2004-07-15",
        gender="MALE",
        mobile="9811122233",
        email="rajesh.sharma@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
    )
    _st_f2, en_f2 = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_f2,
        name="Rajeysh Kumar Sharma",
        dob_iso="2004-07-15",
        gender="MALE",
        mobile="9811122233",
        email="rajeysh.sharma@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
    )
    dup_fuzzy = DuplicateCandidate(
        enrollment_a=en_f1.id,
        enrollment_b=en_f2.id,
        match_type="FUZZY",
        score=0.78,
        reasons=["NAME_SIMILARITY_JARO_WINKLER_GE_92", "DOB_EXACT"],
        status="DETECTED",
    )
    db.add(dup_fuzzy)
    db.flush()

    # (d) Twin Pair (Must NOT alert)
    apaar_t1 = generate_valid_apaar("77000000001")
    apaar_t2 = generate_valid_apaar("77000000002")
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_t1,
        name="Rohan Verma",
        dob_iso="2005-04-10",
        gender="MALE",
        mobile="9876500001",
        email="rohan.verma@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
    )
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_t2,
        name="Kavya Verma",
        dob_iso="2005-04-10",
        gender="FEMALE",
        mobile="9876500001",
        email="kavya.verma@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
    )
    # Note: No duplicate case created for twins (verified via test suite)

    # (e) Progression: Completed UG -> Readmitted to PG (No alert)
    apaar_prog = generate_valid_apaar("78000000001")
    # Prior completed degree
    _st_prog, en_prior = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_prog,
        name="Arjun Nair",
        dob_iso="2002-05-18",
        gender="MALE",
        mobile="9821333444",
        email="arjun.nair@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        academic_year="2020-2021",
        status="COMPLETED",
    )
    # Current PG enrollment
    _, en_current = create_demo_student_and_enrollment(
        db=db,
        apaar_id=apaar_prog,
        name="Arjun Nair",
        dob_iso="2002-05-18",
        gender="MALE",
        mobile="9821333444",
        email="arjun.nair.pg@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        academic_year="2024-2025",
        status="ACTIVE",
    )
    # Progression logged as benign (requires_case=False)
    dup_prog = DuplicateCandidate(
        enrollment_a=en_prior.id,
        enrollment_b=en_current.id,
        match_type="PROGRESSION",
        score=0.90,
        reasons=["EXACT_APAAR_HASH", "COMPLETED_PRIOR_ENROLLMENT", "NORMAL_ACADEMIC_PROGRESSION"],
        status="RESOLVED",
    )
    db.add(dup_prog)
    db.flush()

    # -------------------------------------------------------------------------
    # 7. Identity Cases:
    # - PASSED
    # - FAILED(format)
    # - FAILED(mismatch)
    # - NOT_PROVIDED
    # - UNAVAILABLE
    # -------------------------------------------------------------------------
    print("      Seeding simulated identity states...")
    # (a) PASSED
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("79000000001"),
        name="Isha Chatterjee",
        dob_iso="2005-07-25",
        gender="FEMALE",
        mobile="9821555666",
        email="isha.c@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        identity_status="PASSED",
        verified=True,
    )
    # (b) FAILED(format)
    create_demo_student_and_enrollment(
        db=db,
        apaar_id="790000000029",  # Deliberately fails Luhn
        name="Manish Gupta",
        dob_iso="2004-10-14",
        gender="MALE",
        mobile="9821666777",
        email="manish.g@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        identity_status="FAILED",
        verified=False,
    )
    # (c) FAILED(mismatch)
    create_demo_student_and_enrollment(
        db=db,
        apaar_id="987654321015",  # In registry as Priya Patel, DOB 2005-03-21
        name="Priya Patel",
        dob_iso="1998-01-01",     # Mismatched DOB planted
        gender="FEMALE",
        mobile="9821777888",
        email="priya.mismatch@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        identity_status="FAILED",
        verified=False,
    )
    # (d) NOT_PROVIDED
    create_demo_student_and_enrollment(
        db=db,
        apaar_id=None,
        name="Siddharth Rao",
        dob_iso="2005-11-30",
        gender="MALE",
        mobile="9821888999",
        email="siddharth.r@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        identity_status="NOT_PROVIDED",
        status="PROVISIONAL",
        verified=False,
    )
    # (e) UNAVAILABLE
    create_demo_student_and_enrollment(
        db=db,
        apaar_id="000000111222",
        name="Aniket Deshmukh",
        dob_iso="2005-05-15",
        gender="MALE",
        mobile="9821999000",
        email="aniket.d@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        identity_status="UNAVAILABLE",
        status="PENDING",
        verified=False,
    )

    # -------------------------------------------------------------------------
    # 8. Verifiable Credentials:
    # - 1 VALID active credential
    # - 1 EXPIRED credential
    # - 1 REVOKED credential
    # -------------------------------------------------------------------------
    print("      Seeding verifiable credentials (VALID, EXPIRED, REVOKED)...")

    # (a) VALID active credential
    _st_val, en_val = create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("80000000001"),
        name="Pooja Agarwal",
        dob_iso="2004-04-18",
        gender="FEMALE",
        mobile="9828111222",
        email="pooja.a@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="CONFIRMED",
        verified=True,
    )
    issue_credential(
        db=db,
        enrollment_id=en_val.id,
        qualification="Bachelor of Technology in Computer Science and Engineering",
        actor_id=user_map[ROLE_AICTE_ADMIN].id,
    )

    # (b) EXPIRED credential
    _st_exp, en_exp = create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("80000000002"),
        name="Rohan Nambiar",
        dob_iso="2003-09-12",
        gender="MALE",
        mobile="9828222333",
        email="rohan.n@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="CONFIRMED",
        verified=True,
    )
    cred_expired = issue_credential(
        db=db,
        enrollment_id=en_exp.id,
        qualification="Bachelor of Technology in Computer Science and Engineering",
        actor_id=user_map[ROLE_AICTE_ADMIN].id,
    )
    # Set expires_at in the past
    cred_expired.expires_at = datetime.now(timezone.utc) - timedelta(days=45)
    cred_expired.status = "EXPIRED"
    db.flush()

    # (c) REVOKED credential
    _st_rev, en_rev = create_demo_student_and_enrollment(
        db=db,
        apaar_id=generate_valid_apaar("80000000003"),
        name="Vikas Dubey",
        dob_iso="2004-01-20",
        gender="MALE",
        mobile="9828333444",
        email="vikas.d@iitd.ac.in",
        institution_id=inst_iitd.id,
        approval_id=p_a.id,
        seat_type="REGULAR",
        status="CONFIRMED",
        verified=True,
    )
    cred_revoked = issue_credential(
        db=db,
        enrollment_id=en_rev.id,
        qualification="Bachelor of Technology in Computer Science and Engineering",
        actor_id=user_map[ROLE_AICTE_ADMIN].id,
    )
    revoke_credential(
        db=db,
        credential_id_or_ref=str(cred_revoked.id),
        reason="Admission revoked due to falsified qualifying examination documents",
        actor_id=user_map[ROLE_AICTE_ADMIN].id,
    )

    # Seed registered verifier for employment verification demo
    reg_ver = db.query(RegisteredVerifier).filter(
        RegisteredVerifier.contact_email == "bcv@tcs.com"
    ).first()
    if not reg_ver:
        api_key_plain = "ak_live_tcs_demo_key_2025_sec99"
        api_key_h = hashlib.sha256(api_key_plain.encode("utf-8")).hexdigest()
        reg_ver = RegisteredVerifier(
            name="Tata Consultancy Services Background Verification Cell",
            contact_email="bcv@tcs.com",
            declared_purpose="EMPLOYMENT_VERIFICATION",
            api_key_hash=api_key_h,
            api_key_prefix=api_key_plain[:10],
            rate_limit_per_minute=100,
            allowed_fields=["credential_id", "qualification", "institution_name", "status_at_issue", "issued_at"],
            is_active=True,
        )
        db.add(reg_ver)
        db.flush()

    db.commit()


def main():
    parser = argparse.ArgumentParser(description="AICTE APAAR Connect Demo Database Seeder")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    args = parser.parse_args()

    print("=" * 70)
    print("AICTE APAAR CONNECT - DEMO DATABASE SEEDER")
    print(f"Random Seed:      {args.seed}")
    print(f"Demo Password:    {DEMO_PASSWORD_PLAIN}")
    print("=" * 70)

    # Determinism
    rng = random.Random(args.seed)
    Faker.seed(args.seed)
    faker = Faker("en_IN")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("[1/4] Seeding 2 institutions (+1 spare)...")
        inst_map = seed_institutions(db)
        print(f"      Seeded: {list(inst_map.keys())}")

        print("[2/4] Seeding 7 RBAC demo users...")
        user_map = seed_demo_users(db, inst_map)
        print(f"      Seeded {len(user_map)} users with demo password: {DEMO_PASSWORD_PLAIN}")

        print("[3/4] Seeding 3 approved programmes & seat matrices...")
        approvals = seed_programmes_and_seat_matrices(db, inst_map)
        print(f"      Seeded {len(approvals)} programmes")

        print("[4/4] Seeding demonstration enrollments, life-cycles & edge cases...")
        seed_demo_scenarios(
            db=db,
            inst_map=inst_map,
            approvals=approvals,
            user_map=user_map,
            faker=faker,
            rng=rng,
        )

        print("=" * 70)
        print("[SUCCESS] Demonstration database seeded cleanly and successfully!")
        print("=" * 70)

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
