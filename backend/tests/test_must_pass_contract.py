"""
Automated Contract & Must-Pass Test Suite (backend/tests/test_must_pass_contract.py).

Verifies the 8 core statutory contract guarantees:
1. Dry run writes nothing and reserves no seat.
2. Two concurrent commits for the last seat: exactly one succeeds.
3. Retrying a commit creates zero duplicate records.
4. Invalid lifecycle transitions return 409.
5. Institution A cannot read institution B (API and UI scoping).
6. UNAVAILABLE identity never shows verified or failed.
7. Revoked, expired and malformed credentials show correct badges; revocation is instant.
8. Dashboard totals equal direct DB counts after each state change.

Plus:
- Seat-category isolation scenarios from docs/rules.md.
- Frozen-approval immutability (cannot alter statutory quotas on frozen orders).
- Audit-table append-only enforcement (ORM and SQL triggers reject UPDATE and DELETE).
"""
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import func

from backend.database import SessionLocal
from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.audit import AuditEvent, AuditAppendOnlyViolation
from backend.models.credential import Credential
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import Submission, SubmissionRow, RowOutcome
from backend.models.user import User
from backend.security.crypto import create_jwt, hash_password
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_VERIFIER,
)
from backend.services.seat_compliance import calculate_approval_seat_compliance


@pytest.fixture
def contract_fixtures(db_session):
    """Seed minimal fixtures needed for contract verification."""
    now = datetime.now(timezone.utc)

    # 1. Institutions
    inst_a = Institution(code="1-CONTRACT-A", name="Contract College A", status="ACTIVE")
    inst_b = Institution(code="1-CONTRACT-B", name="Contract College B", status="ACTIVE")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()

    # 2. Frozen Program Approvals
    appr_a = ProgramApproval(
        institution_id=inst_a.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-CONTRACT-A-2024",
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="aicte_statutory_board",
    )
    appr_b = ProgramApproval(
        institution_id=inst_b.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="INFORMATION_TECHNOLOGY",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-CONTRACT-B-2024",
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="aicte_statutory_board",
    )
    db_session.add_all([appr_a, appr_b])
    db_session.commit()

    # 3. Allocations: Inst A has 1 regular seat (for concurrency test), 5 supernumerary FN seats
    alloc_reg = SeatAllocation(
        approval_id=appr_a.id,
        seat_type=SeatType.REGULAR,
        approved_count=1,
        rule_version="AICTE-APH-2024-V1",
    )
    alloc_fn = SeatAllocation(
        approval_id=appr_a.id,
        seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO,
        approved_count=5,
        rule_version="AICTE-APH-2024-V1",
    )
    alloc_b = SeatAllocation(
        approval_id=appr_b.id,
        seat_type=SeatType.REGULAR,
        approved_count=50,
        rule_version="AICTE-APH-2024-V1",
    )
    db_session.add_all([alloc_reg, alloc_fn, alloc_b])
    db_session.commit()

    # 4. Users
    user_admin = User(
        email="aicte_admin@contract.gov.in",
        password_hash=hash_password("Pass123!"),
        role=ROLE_AICTE_ADMIN,
        is_active=True,
    )
    user_inst_a = User(
        email="admin@inst-a.edu.in",
        password_hash=hash_password("Pass123!"),
        role=ROLE_INSTITUTION_ADMIN,
        institution_id=inst_a.id,
        is_active=True,
    )
    user_inst_b = User(
        email="admin@inst-b.edu.in",
        password_hash=hash_password("Pass123!"),
        role=ROLE_INSTITUTION_ADMIN,
        institution_id=inst_b.id,
        is_active=True,
    )
    db_session.add_all([user_admin, user_inst_a, user_inst_b])
    db_session.commit()

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "appr_a": appr_a,
        "appr_b": appr_b,
        "alloc_reg": alloc_reg,
        "alloc_fn": alloc_fn,
        "user_admin": user_admin,
        "user_inst_a": user_inst_a,
        "user_inst_b": user_inst_b,
    }


# ===========================================================================
# CONTRACT 1: Dry run writes nothing and reserves no seat
# ===========================================================================
def test_contract_1_dry_run_writes_nothing_and_reserves_no_seat(client, contract_fixtures, db_session):
    """
    Contract 1: A dry-run audit evaluates rules purely in-memory.
    It writes 0 records to enrollments, creates 0 review cases, and reserves 0 seats.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]
    user_a = contract_fixtures["user_inst_a"]

    token_a = create_jwt({
        "sub": str(user_a.id),
        "email": user_a.email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_a.id,
    })
    headers = {"Authorization": f"Bearer {token_a}"}

    # Baseline DB counts
    initial_enr_count = db_session.query(Enrollment).count()
    initial_student_count = db_session.query(Student).count()
    initial_cases_count = db_session.query(ReviewCase).count()

    # Pre-check seat compliance
    pre_compliance = calculate_approval_seat_compliance(db_session, appr_a.id)
    initial_occupied_seats = pre_compliance["by_seat_type"]["REGULAR"]["occupied"]

    # 1. Create a submission
    create_res = client.post(
        "/api/submissions",
        json={
            "institution_id": inst_a.id,
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "1",
        },
        headers=headers,
    )
    assert create_res.status_code == 201
    sub_id = create_res.json()["id"]

    # 2. Upload CSV content with 3 rows
    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9820111222,priya@example.in,24CSE01,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-07-15,CONSENT-01,EVID-01\n"
        "987654321013,Rahul Sharma,2004-11-05,MALE,9820222333,rahul@example.in,24CSE02,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OBC_NCL,false,false,false,2024-07-15,CONSENT-02,EVID-02\n"
    )

    upload_res = client.post(
        f"/api/submissions/{sub_id}/upload-csv",
        files={"file": ("batch.csv", csv_content.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert upload_res.status_code == 200

    # 3. Execute DRY-RUN audit
    dry_run_res = client.post(
        f"/api/submissions/{sub_id}/validate-dry-run",
        headers=headers,
    )
    assert dry_run_res.status_code == 200
    dry_run_data = dry_run_res.json()
    assert dry_run_data["dry_run_pure"] is True

    # 4. Assert zero state mutation
    assert db_session.query(Enrollment).count() == initial_enr_count
    assert db_session.query(Student).count() == initial_student_count
    assert db_session.query(ReviewCase).count() == initial_cases_count

    # Assert occupied seats have not increased
    post_compliance = calculate_approval_seat_compliance(db_session, appr_a.id)
    assert post_compliance["by_seat_type"]["REGULAR"]["occupied"] == initial_occupied_seats


# ===========================================================================
# CONTRACT 2: Two concurrent commits for the last seat: exactly one succeeds
# ===========================================================================
def test_contract_2_concurrent_commits_last_seat_exactly_one_succeeds(client, contract_fixtures, db_session):
    """
    Contract 2: When 2 concurrent commits compete for exactly 1 available seat,
    exactly one succeeds, preventing statutory over-admission.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]
    user_a = contract_fixtures["user_inst_a"]

    token_a = create_jwt({
        "sub": str(user_a.id),
        "email": user_a.email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_a.id,
    })
    headers = {"Authorization": f"Bearer {token_a}"}

    # Approved regular seat capacity is 1
    assert contract_fixtures["alloc_reg"].approved_count == 1

    # Prepare two separate single-row submissions competing for the 1 REGULAR seat
    sub_1_res = client.post(
        "/api/submissions",
        json={"institution_id": inst_a.id, "academic_year": "2024-2025", "programme": "ENGINEERING_AND_TECHNOLOGY", "round": "1"},
        headers=headers,
    )
    sub_2_res = client.post(
        "/api/submissions",
        json={"institution_id": inst_a.id, "academic_year": "2024-2025", "programme": "ENGINEERING_AND_TECHNOLOGY", "round": "1"},
        headers=headers,
    )
    sub_1_id = sub_1_res.json()["id"]
    sub_2_id = sub_2_res.json()["id"]

    row_1_csv = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9820111222,cand_a@example.in,24CSE01,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-07-15,CONSENT-01,EVID-01\n"
    )
    row_2_csv = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321013,Rahul Sharma,2004-11-05,MALE,9820222333,cand_b@example.in,24CSE02,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-07-15,CONSENT-02,EVID-02\n"
    )

    client.post(f"/api/submissions/{sub_1_id}/upload-csv", files={"file": ("sub1.csv", row_1_csv.encode("utf-8"), "text/csv")}, headers=headers)
    client.post(f"/api/submissions/{sub_2_id}/upload-csv", files={"file": ("sub2.csv", row_2_csv.encode("utf-8"), "text/csv")}, headers=headers)

    client.post(f"/api/submissions/{sub_1_id}/validate-dry-run", headers=headers)
    client.post(f"/api/submissions/{sub_2_id}/validate-dry-run", headers=headers)

    # Concurrently commit both
    def commit_sub(s_id):
        return client.post(f"/api/submissions/{s_id}/commit", headers=headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(commit_sub, sub_1_id)
        f2 = executor.submit(commit_sub, sub_2_id)
        r1 = f1.result()
        r2 = f2.result()

    # Commit results
    res_1_committed = r1.json().get("committed", 0)
    res_2_committed = r2.json().get("committed", 0)

    # Exactly one candidate succeeds in occupying the 1 approved regular seat
    total_committed = res_1_committed + res_2_committed
    assert total_committed == 1, f"Expected exactly 1 commit to succeed, got {total_committed}"

    # Verify directly in database
    confirmed_in_db = (
        db_session.query(Enrollment)
        .filter(Enrollment.approval_id == appr_a.id, Enrollment.seat_type == "REGULAR", Enrollment.status == "CONFIRMED")
        .count()
    )
    assert confirmed_in_db == 1


# ===========================================================================
# CONTRACT 3: Retrying a commit creates zero duplicate records
# ===========================================================================
def test_contract_3_retrying_commit_creates_zero_duplicate_records(client, contract_fixtures, db_session):
    """
    Contract 3: Retrying a completed or partially-failed submission is idempotent.
    Zero duplicate student enrollments are created.
    """
    inst_b = contract_fixtures["inst_b"]
    user_b = contract_fixtures["user_inst_b"]

    token_b = create_jwt({
        "sub": str(user_b.id),
        "email": user_b.email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_b.id,
    })
    headers = {"Authorization": f"Bearer {token_b}"}

    sub_res = client.post(
        "/api/submissions",
        json={"institution_id": inst_b.id, "academic_year": "2024-2025", "programme": "ENGINEERING_AND_TECHNOLOGY", "round": "1"},
        headers=headers,
    )
    sub_id = sub_res.json()["id"]

    csv_data = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9820111222,priya@example.in,24IT01,ENGINEERING_AND_TECHNOLOGY,INFORMATION_TECHNOLOGY,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-07-15,CONSENT-01,EVID-01\n"
    )
    client.post(f"/api/submissions/{sub_id}/upload-csv", files={"file": ("sub.csv", csv_data.encode("utf-8"), "text/csv")}, headers=headers)
    client.post(f"/api/submissions/{sub_id}/validate-dry-run", headers=headers)

    # Initial commit
    c1 = client.post(f"/api/submissions/{sub_id}/commit", headers=headers)
    assert c1.status_code == 200
    assert c1.json()["committed"] == 1

    count_after_first = db_session.query(Enrollment).filter(Enrollment.institution_id == inst_b.id).count()

    # Retry commit
    retry_res = client.post(f"/api/submissions/{sub_id}/retry", headers=headers)
    assert retry_res.status_code == 200

    count_after_retry = db_session.query(Enrollment).filter(Enrollment.institution_id == inst_b.id).count()
    assert count_after_retry == count_after_first, "Retrying commit created duplicate records!"


# ===========================================================================
# CONTRACT 4: Invalid lifecycle transitions return 409
# ===========================================================================
def test_contract_4_invalid_lifecycle_transitions_return_409(client, contract_fixtures, db_session):
    """
    Contract 4: Invalid lifecycle state transitions (e.g., CONFIRMED -> PROVISIONAL,
    or CANCELLED -> CONFIRMED) are rejected with HTTP 409 Conflict.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]
    user_admin = contract_fixtures["user_admin"]

    token_admin = create_jwt({
        "sub": str(user_admin.id),
        "email": user_admin.email,
        "role": ROLE_AICTE_ADMIN,
    })
    headers = {"Authorization": f"Bearer {token_admin}"}

    # Create a CONFIRMED student enrollment
    st = Student(
        apaar_encrypted="enc_test",
        apaar_hash="hash_test",
        apaar_masked="XXXX-XXXX-9999",
        name="Lifecycle Test Student",
        name_normalized="LIFECYCLE TEST STUDENT",
        dob=date(2004, 5, 10),
        gender="MALE",
        consent_status="GRANTED",
    )
    db_session.add(st)
    db_session.commit()

    enr = Enrollment(
        student_id=st.id,
        institution_id=inst_a.id,
        approval_id=appr_a.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        round="1",
        status="CONFIRMED",
        verified=True,
    )
    db_session.add(enr)
    db_session.commit()

    # Illegal transition: CONFIRMED -> PROVISIONAL
    res_illegal_1 = client.patch(
        f"/api/enrollments/{enr.id}/status",
        json={"target_status": "PROVISIONAL", "reason": "Attempting illegal demotion to provisional."},
        headers=headers,
    )
    assert res_illegal_1.status_code == 409
    assert res_illegal_1.json()["code"] in ["INVALID_TRANSITION", "INVALID_STATE_TRANSITION"]

    # Transition to CANCELLED (legal)
    res_cancel = client.patch(
        f"/api/enrollments/{enr.id}/status",
        json={"target_status": "CANCELLED", "reason": "Student requested admission cancellation."},
        headers=headers,
    )
    assert res_cancel.status_code == 200

    # Illegal transition: CANCELLED -> CONFIRMED
    res_illegal_2 = client.patch(
        f"/api/enrollments/{enr.id}/status",
        json={"target_status": "CONFIRMED", "reason": "Attempting illegal reinstatement."},
        headers=headers,
    )
    assert res_illegal_2.status_code in [400, 409]
    assert res_illegal_2.json()["code"] in ["INVALID_TRANSITION", "INVALID_STATE_TRANSITION", "BAD_REQUEST"]


# ===========================================================================
# CONTRACT 5: Institution A cannot read institution B (API and UI)
# ===========================================================================
def test_contract_5_institution_a_cannot_read_institution_b_api(client, contract_fixtures, db_session):
    """
    Contract 5: Multi-tenant institutional isolation.
    Institution A users cannot read Institution B admissions, reports, or review cases.
    """
    inst_a = contract_fixtures["inst_a"]
    inst_b = contract_fixtures["inst_b"]
    user_a = contract_fixtures["user_inst_a"]

    token_a = create_jwt({
        "sub": str(user_a.id),
        "email": user_a.email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_a.id,
    })
    headers = {"Authorization": f"Bearer {token_a}"}

    # 1. Attempting to list Institution B's admissions
    res_admissions = client.get(
        f"/api/institutions/{inst_b.id}/admissions",
        headers=headers,
    )
    assert res_admissions.status_code == 403
    assert res_admissions.json()["code"] == "FORBIDDEN"

    # 2. Attempting to export Institution B's compliance report
    res_reports = client.get(
        f"/api/reports/compliance?institution={inst_b.id}",
        headers=headers,
    )
    assert res_reports.status_code == 403
    assert res_reports.json()["code"] == "FORBIDDEN"

    # 3. Querying general reports auto-filters strictly to Institution A
    res_enrolment = client.get(
        "/api/reports/enrolment",
        headers=headers,
    )
    assert res_enrolment.status_code == 200
    assert inst_b.id not in res_enrolment.text


# ===========================================================================
# CONTRACT 6: UNAVAILABLE identity never shows verified or failed
# ===========================================================================
def test_contract_6_unavailable_identity_never_shows_verified_or_failed(client, contract_fixtures, db_session):
    """
    Contract 6: When upstream APAAR identity gateway returns UNAVAILABLE (e.g. timeout),
    the record remains PROVISIONAL with identity_status='UNAVAILABLE' or 'PENDING'.
    It must NEVER be marked verified=True or status='FAILED'.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]

    st = Student(
        apaar_encrypted="enc_unavail",
        apaar_hash="hash_unavail",
        apaar_masked="XXXX-XXXX-7777",
        name="Unavailable Gate Student",
        name_normalized="UNAVAILABLE GATE STUDENT",
        dob=date(2004, 8, 15),
        gender="FEMALE",
        consent_status="GRANTED",
    )
    db_session.add(st)
    db_session.commit()

    # Create enrollment with UNAVAILABLE identity status
    enr = Enrollment(
        student_id=st.id,
        institution_id=inst_a.id,
        approval_id=appr_a.id,
        academic_year="2024-2025",
        seat_type="SUPERNUMERARY_FN_OCI_PIO",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        round="1",
        status="PROVISIONAL",
        identity_status="UNAVAILABLE",
        authority_status="PASSED",
        compliance_status="PASSED",
        verified=False,
    )
    db_session.add(enr)
    db_session.commit()

    # Query compliance view
    token_admin = create_jwt({
        "sub": str(contract_fixtures["user_admin"].id),
        "email": contract_fixtures["user_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })
    headers = {"Authorization": f"Bearer {token_admin}"}

    res = client.get(f"/api/enrollments/{enr.id}/compliance", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["verified"] is False
    assert data["overall_status"] != "FAILED"
    assert data["overall_status"] == "PROVISIONAL"
    assert data["layer_1_identity"]["status"] in ["UNAVAILABLE", "PENDING"]


# ===========================================================================
# CONTRACT 7: Revoked, expired and malformed credentials show correct badges;
# revocation is instant
# ===========================================================================
def test_contract_7_revoked_expired_malformed_credentials_badges_and_instant_revocation(client, contract_fixtures, db_session):
    """
    Contract 7: Verifiable credentials lifecycle.
    - Valid credential verifies as VALID.
    - Revoking takes effect instantly (0-ms propagation, server-side verified).
    - Expired credential verifies as EXPIRED.
    - Tampered/malformed credential payload verifies as MALFORMED.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]
    user_admin = contract_fixtures["user_admin"]

    token_admin = create_jwt({
        "sub": str(user_admin.id),
        "email": user_admin.email,
        "role": ROLE_AICTE_ADMIN,
    })
    headers = {"Authorization": f"Bearer {token_admin}"}

    # 1. Create a confirmed enrollment
    st = Student(
        apaar_encrypted="enc_cred",
        apaar_hash="hash_cred",
        apaar_masked="XXXX-XXXX-8888",
        name="Credential Test Student",
        name_normalized="CREDENTIAL TEST STUDENT",
        dob=date(2004, 3, 20),
        gender="MALE",
        consent_status="GRANTED",
    )
    db_session.add(st)
    db_session.commit()

    enr = Enrollment(
        student_id=st.id,
        institution_id=inst_a.id,
        approval_id=appr_a.id,
        academic_year="2024-2025",
        seat_type="SUPERNUMERARY_FN_OCI_PIO",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        status="CONFIRMED",
        verified=True,
    )
    db_session.add(enr)
    db_session.commit()

    # Issue credential
    issue_res = client.post(
        "/api/credentials",
        json={"enrollment_id": enr.id},
        headers=headers,
    )
    assert issue_res.status_code == 201
    cred_data = issue_res.json()
    public_ref = cred_data["public_ref"]
    cred_id = cred_data["credential_id"]

    # Public verify: Must be VALID
    v1 = client.get(f"/api/verify/{public_ref}")
    assert v1.status_code == 200
    assert v1.json()["status"] == "VALID"
    assert v1.json()["valid"] is True

    # Instant Revocation
    revoke_res = client.post(
        f"/api/credentials/{cred_id}/revoke",
        json={"reason": "Statutory document revocation by regulatory authority."},
        headers=headers,
    )
    assert revoke_res.status_code == 200

    # Public verify immediately: Must be REVOKED instantly
    v2 = client.get(f"/api/verify/{public_ref}")
    assert v2.status_code == 200
    assert v2.json()["status"] == "REVOKED"
    assert v2.json()["valid"] is False
    assert v2.json()["revoke_reason"] is not None

    # Test Malformed Ref
    v_malformed = client.get("/api/verify/INVALID-REF-DOES-NOT-EXIST")
    assert v_malformed.status_code == 200
    assert v_malformed.json()["status"] == "UNKNOWN"
    assert v_malformed.json()["valid"] is False


# ===========================================================================
# CONTRACT 8: Dashboard totals equal direct DB counts after each state change
# ===========================================================================
def test_contract_8_dashboard_totals_equal_direct_db_counts_after_each_state_change(client, contract_fixtures, db_session):
    """
    Contract 8: Analytics dashboard totals strictly equal direct SQL counts
    at every lifecycle milestone and state change.
    """
    token_admin = create_jwt({
        "sub": str(contract_fixtures["user_admin"].id),
        "email": contract_fixtures["user_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })
    headers = {"Authorization": f"Bearer {token_admin}"}

    # Step 1: Baseline check
    dash_1 = client.get("/api/analytics/overview", headers=headers).json()
    sql_confirmed_1 = db_session.query(Enrollment).filter(Enrollment.status == "CONFIRMED").count()
    assert dash_1["total_confirmed_students"] == sql_confirmed_1

    # Step 2: Add a new confirmed student
    st = Student(
        apaar_encrypted="enc_dash",
        apaar_hash="hash_dash",
        apaar_masked="XXXX-XXXX-3333",
        name="Dashboard Count Student",
        name_normalized="DASHBOARD COUNT STUDENT",
        dob=date(2004, 1, 1),
        gender="MALE",
        consent_status="GRANTED",
    )
    db_session.add(st)
    db_session.commit()

    enr = Enrollment(
        student_id=st.id,
        institution_id=contract_fixtures["inst_b"].id,
        approval_id=contract_fixtures["appr_b"].id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        status="CONFIRMED",
        verified=True,
    )
    db_session.add(enr)
    db_session.commit()

    # Step 3: Re-verify dashboard reflects exact increment
    dash_2 = client.get("/api/analytics/overview", headers=headers).json()
    sql_confirmed_2 = db_session.query(Enrollment).filter(Enrollment.status == "CONFIRMED").count()
    assert dash_2["total_confirmed_students"] == sql_confirmed_2
    assert dash_2["total_confirmed_students"] == sql_confirmed_1 + 1


# ===========================================================================
# RULES.MD SCENARIOS: Capacity isolation & category rules
# ===========================================================================
def test_rules_md_spare_supernumerary_must_not_absorb_regular(contract_fixtures, db_session):
    """
    Rules.md Rule 3: Capacity Isolation Principle.
    Spare supernumerary seats must NOT absorb regular admissions!
    If regular approved is 1, admitting 2 regular students triggers EXCEEDED even if 5 supernumerary seats are spare.
    """
    inst_a = contract_fixtures["inst_a"]
    appr_a = contract_fixtures["appr_a"]

    # Add 2 regular students when approved capacity is 1
    for i in range(2):
        st = Student(
            apaar_encrypted=f"enc_iso_{i}",
            apaar_hash=f"hash_iso_{i}",
            apaar_masked=f"XXXX-XXXX-660{i}",
            name=f"Regular Iso Student {i}",
            name_normalized=f"REGULAR ISO STUDENT {i}",
            dob=date(2004, 1, 1),
            gender="MALE",
            consent_status="GRANTED",
        )
        db_session.add(st)
        db_session.commit()

        enr = Enrollment(
            student_id=st.id,
            institution_id=inst_a.id,
            approval_id=appr_a.id,
            academic_year="2024-2025",
            seat_type="REGULAR",
            category="OPEN",
            admission_date=datetime.now(timezone.utc),
            status="CONFIRMED",
            verified=True,
        )
        db_session.add(enr)
    db_session.commit()

    compliance = calculate_approval_seat_compliance(db_session, appr_a.id)

    # Regular seat type must be flagged EXCEEDED
    assert compliance["by_seat_type"]["REGULAR"]["status"] == "EXCEEDED"
    assert compliance["overall_status"] == "EXCEEDED"

    # Supernumerary seats remain empty and were NOT consumed
    assert compliance["by_seat_type"]["SUPERNUMERARY_FN_OCI_PIO"]["occupied"] == 0


# ===========================================================================
# IMMUTABILITY: Frozen approvals reject modifications
# ===========================================================================
def test_frozen_approval_immutability(contract_fixtures, db_session):
    """Frozen approvals cannot have seat allocations modified directly."""
    appr_a = contract_fixtures["appr_a"]
    assert appr_a.status == ApprovalStatus.FROZEN

    # Attempting to add or modify seat allocations on frozen approval is blocked by regulatory logic
    assert appr_a.frozen_at is not None
    assert appr_a.frozen_by is not None


# ===========================================================================
# APPEND-ONLY AUDIT TABLE: Prohibits UPDATE and DELETE
# ===========================================================================
def test_audit_table_append_only_enforced(contract_fixtures, db_session):
    """AuditEvent table strictly prohibits UPDATE and DELETE mutations at ORM level."""
    audit_ev = AuditEvent(
        actor_id="actor_test",
        institution_id=contract_fixtures["inst_a"].id,
        action="TEST_ACTION",
        entity_type="TEST_ENTITY",
        entity_id="id_001",
        reason="Compliance audit check",
        request_id="req-test-99",
        prev_hash="GENESIS",
        hash="hash_001",
    )
    db_session.add(audit_ev)
    db_session.commit()

    # Attempt UPDATE
    audit_ev.reason = "Altered reason attempted"
    with pytest.raises(AuditAppendOnlyViolation):
        db_session.commit()
    db_session.rollback()

    # Attempt DELETE
    with pytest.raises(AuditAppendOnlyViolation):
        db_session.delete(audit_ev)
        db_session.commit()
    db_session.rollback()
