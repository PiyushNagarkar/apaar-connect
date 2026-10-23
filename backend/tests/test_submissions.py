import concurrent.futures
import io
from datetime import date, datetime, timezone
import pytest
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import RowOutcome, Submission, SubmissionRow
from backend.models.user import User
from backend.security.crypto import create_jwt


@pytest.fixture
def submission_setup(db_session: Session):
    """
    Sets up two test institutions, users, and a frozen program approval with seats.
    """
    # 1. Institutions
    inst_a = Institution(code="1-SUB-A", name="College of Engineering Alpha", status="ACTIVE")
    inst_b = Institution(code="1-SUB-B", name="Institute of Tech Beta", status="ACTIVE")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()

    # 2. Users
    user_a = User(
        email="operator@alpha.edu",
        password_hash="hash_a",
        role="INSTITUTION_OPERATOR",
        institution_id=inst_a.id,
        is_active=True,
    )
    user_b = User(
        email="operator@beta.edu",
        password_hash="hash_b",
        role="INSTITUTION_OPERATOR",
        institution_id=inst_b.id,
        is_active=True,
    )
    admin = User(
        email="admin@aicte.gov.in",
        password_hash="hash_admin",
        role="AICTE_ADMIN",
        institution_id=None,
        is_active=True,
    )
    db_session.add_all([user_a, user_b, admin])
    db_session.commit()

    # 3. Frozen Approval for Inst A: CSE 2024-2025
    now = datetime.now(timezone.utc)
    approval_a = ProgramApproval(
        institution_id=inst_a.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-ALPHA-2024-001",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by=admin.id,
    )
    db_session.add(approval_a)
    db_session.commit()

    # Seat allocations: 60 regular, 5 NRI
    alloc_reg = SeatAllocation(
        approval_id=approval_a.id,
        seat_type=SeatType.REGULAR,
        approved_count=60,
        rule_version="AICTE_2024_25",
    )
    alloc_nri = SeatAllocation(
        approval_id=approval_a.id,
        seat_type=SeatType.NRI,
        approved_count=5,
        rule_version="AICTE_2024_25",
    )
    db_session.add_all([alloc_reg, alloc_nri])
    db_session.commit()

    token_a = create_jwt({"sub": str(user_a.id), "email": user_a.email, "role": user_a.role, "institution_id": str(inst_a.id)})
    token_b = create_jwt({"sub": str(user_b.id), "email": user_b.email, "role": user_b.role, "institution_id": str(inst_b.id)})
    token_admin = create_jwt({"sub": str(admin.id), "email": admin.email, "role": admin.role})

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "user_a": user_a,
        "user_b": user_b,
        "admin": admin,
        "approval_a": approval_a,
        "alloc_reg": alloc_reg,
        "token_a": token_a,
        "token_b": token_b,
        "token_admin": token_admin,
    }


# ---------------------------------------------------------------------------
# 1. Dry Run Purity Test
# ---------------------------------------------------------------------------

def test_dry_run_purity(client, submission_setup, db_session):
    """
    CRITICAL SEMANTICS:
    Dry run writes NOTHING except validation results; it reserves no seats.
    Verifies that validating a submission does NOT create students or enrollments.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    # Create submission
    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "dry-run-key-01",
        },
    )
    assert res_create.status_code == 201
    sub_id = res_create.json()["id"]

    # Upload valid CSV
    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9876543210,priya@example.com,R101,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
    )
    res_upload = client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )
    assert res_upload.status_code == 200

    # Execute Dry-Run Validation
    res_val = client.post(
        f"/api/submissions/{sub_id}/validate",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_val.status_code == 200
    val_data = res_val.json()
    assert val_data["status"] == "VALIDATED"
    assert val_data["valid_rows"] == 1
    assert val_data["invalid_rows"] == 0
    assert val_data["dry_run"] is True

    # Critical Purity Check: NO enrollments, NO students, NO seats reserved
    enrollments_count = db_session.query(Enrollment).count()
    students_count = db_session.query(Student).count()
    assert enrollments_count == 0, "Dry run must NOT insert any enrollments!"
    assert students_count == 0, "Dry run must NOT insert any students!"


# ---------------------------------------------------------------------------
# 2. Concurrency on Last Seat Test (Threads)
# ---------------------------------------------------------------------------

def test_concurrency_on_last_seat_threads(client, submission_setup, db_session):
    """
    Two concurrent commits for the last seat: exactly one succeeds.
    Setup approval with approved_count = 1.
    Run two parallel requests competing for this 1 available seat.
    """
    inst_a = submission_setup["inst_a"]
    token_a = submission_setup["token_a"]
    admin = submission_setup["admin"]

    # Create dedicated branch DATA_SCIENCE with approved_count = 1 before freezing
    now = datetime.now(timezone.utc)
    approval_ds = ProgramApproval(
        institution_id=inst_a.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="DATA_SCIENCE",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-ALPHA-DS-2024",
        version=1,
        status=ApprovalStatus.DRAFT,
    )
    db_session.add(approval_ds)
    db_session.commit()

    alloc_ds = SeatAllocation(
        approval_id=approval_ds.id,
        seat_type=SeatType.REGULAR,
        approved_count=1,
        rule_version="AICTE_2024_25",
    )
    db_session.add(alloc_ds)
    db_session.commit()

    # Freeze the approval
    approval_ds.status = ApprovalStatus.FROZEN
    approval_ds.frozen_at = now
    approval_ds.frozen_by = admin.id
    db_session.commit()

    student_req_1 = {
        "institution_id": str(inst_a.id),
        "apaar_id": "987654321015",
        "name": "Priya Patel",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "mobile": "9876543210",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "DATA_SCIENCE",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "admission_date": "2024-08-01",
    }
    student_req_2 = {
        "institution_id": str(inst_a.id),
        "apaar_id": "123456789012",
        "name": "Aarav Sharma",
        "dob": "2004-05-14",
        "gender": "MALE",
        "mobile": "9876543211",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "DATA_SCIENCE",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "admission_date": "2024-08-01",
    }

    results = []

    def send_admission(payload):
        res = client.post(
            "/api/students",
            headers={"Authorization": f"Bearer {token_a}"},
            json=payload,
        )
        return res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(send_admission, student_req_1)
        f2 = executor.submit(send_admission, student_req_2)
        results = [f1.result(), f2.result()]

    status_codes = [r[0] for r in results]

    # Exactly one succeeded (201) and one failed (409 Conflict - capacity exceeded)
    assert 201 in status_codes, f"Expected one successful admission, got: {status_codes}"
    assert 409 in status_codes, f"Expected one 409 Conflict, got: {status_codes}"

    # Confirm exactly 1 enrollment was committed in the database
    committed_count = (
        db_session.query(Enrollment)
        .filter(Enrollment.approval_id == approval_ds.id, Enrollment.seat_type == "REGULAR")
        .count()
    )
    assert committed_count == 1, "Exactly one seat should be occupied!"



# ---------------------------------------------------------------------------
# 3. Idempotent Retry Test
# ---------------------------------------------------------------------------

def test_idempotent_retry(client, submission_setup, db_session):
    """
    Retry is idempotent via row_key = hash(institution, year, programme, apaar_hash, round).
    Retrying never double-inserts.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    # 1. Create submission
    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "idempotent-retry-test-01",
        },
    )
    sub_id = res_create.json()["id"]

    # 2. Upload CSV with 1 valid row
    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9876543210,priya@example.com,R102,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
    )
    client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )

    # 3. First commit
    res_commit1 = client.post(
        f"/api/submissions/{sub_id}/commit",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_commit1.status_code == 200
    assert res_commit1.json()["committed"] == 1
    assert db_session.query(Enrollment).count() == 1

    # 4. Retry submission
    res_retry = client.post(
        f"/api/submissions/{sub_id}/retry",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_retry.status_code == 200
    assert res_retry.json()["committed"] == 1

    # Total enrollments in DB MUST remain 1; no duplicate row created!
    assert db_session.query(Enrollment).count() == 1


# ---------------------------------------------------------------------------
# 4. Partial Failure Reporting Test
# ---------------------------------------------------------------------------

def test_partial_failure_reporting(client, submission_setup, db_session):
    """
    Row outcomes reported separately: COMMITTED / FAILED / UNPROCESSED.
    If some rows fail, committed rows stay committed and the rest are reported truthfully.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "partial-fail-key-01",
        },
    )
    sub_id = res_create.json()["id"]

    # CSV with 2 rows:
    # Row 1: Valid
    # Row 2: Invalid (nri_flag and fn_flag both true -> CONTRADICTORY_FLAGS)
    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9876543210,priya@example.com,R103,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
        "123456789012,Aarav Sharma,2004-05-14,MALE,9876543211,aarav@example.com,R104,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,true,false,true,2024-08-01,CONSENT-02,DOC-02\n"
    )
    client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )

    # Commit
    res_commit = client.post(
        f"/api/submissions/{sub_id}/commit",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_commit.status_code == 200
    commit_data = res_commit.json()
    assert commit_data["status"] == "PARTIALLY_FAILED"
    assert commit_data["committed"] == 1
    assert commit_data["failed"] == 1

    # Verify per-row errors endpoint
    res_errors = client.get(
        f"/api/submissions/{sub_id}/errors",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_errors.status_code == 200
    errors = res_errors.json()
    assert len(errors) >= 1
    assert any(e["error_code"] == "CONTRADICTORY_FLAGS" for e in errors)

    # Verify committed row is in database
    committed_enrollments = db_session.query(Enrollment).count()
    assert committed_enrollments == 1


# ---------------------------------------------------------------------------
# 5. CSV Injection Sanitization Test
# ---------------------------------------------------------------------------

def test_csv_injection_sanitization(client, submission_setup, db_session):
    """
    Formula-injection sanitising for cells starting with = + - @.
    Must prefix with a single quote ' to prevent spreadsheet code execution.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "csv-injection-key-01",
        },
    )
    sub_id = res_create.json()["id"]

    # CSV with formula injection attempts
    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "=cmd|' /C calc'!A0,+SUM(1;2),2005-03-21,FEMALE,-9876543210,@DDE('a';'b';'c'),R105,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
    )
    res_upload = client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )
    assert res_upload.status_code == 200

    row = db_session.query(SubmissionRow).filter(SubmissionRow.submission_id == sub_id).first()
    assert row is not None

    # Check raw parsed cells for formula sanitization
    raw = row.raw
    assert raw["apaar_id"].startswith("'="), "Cell starting with '=' must be prefixed with quote"
    assert raw["name"].startswith("'+"), "Cell starting with '+' must be prefixed with quote"
    assert raw["mobile"].startswith("'-"), "Cell starting with '-' must be prefixed with quote"
    assert raw["email"].startswith("'@"), "Cell starting with '@' must be prefixed with quote"


# ---------------------------------------------------------------------------
# 6. Wrong-Institution Submission Rejected Test
# ---------------------------------------------------------------------------

def test_wrong_institution_submission_rejected(client, submission_setup):
    """
    Rule 7: Institution users automatically get a filter on institution_id.
    Operator from Institution A submitting or accessing Institution B is rejected with 403 Forbidden.
    """
    token_a = submission_setup["token_a"]  # User belonging to inst_a
    inst_b = submission_setup["inst_b"]    # Institution B

    # Attempt to create submission for Institution B using token for Institution A
    res = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_b.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "wrong-inst-key-01",
        },
    )
    assert res.status_code == 403
    data = res.json()
    assert "code" in data
    assert data["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# 7. Round Lock Control & Reason Codes Test
# ---------------------------------------------------------------------------

def test_round_lock_requires_reason_code(client, submission_setup, db_session):
    """
    After lock, edits need a reason code:
    (DATA_ENTRY_ERROR, OFFICIAL_CORRECTION, TRANSFER_UPDATE, WITHDRAWAL_UPDATE,
    APPROVAL_UPDATE, OTHER_REQUIRES_EXPLANATION) and are tagged 'late'.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "round-lock-key-01",
        },
    )
    sub_id = res_create.json()["id"]

    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9876543210,priya@example.com,R106,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
    )
    client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )

    # Manually lock the submission round in DB
    sub = db_session.query(Submission).filter(Submission.id == sub_id).first()
    sub.is_locked = True
    sub.lock_reason = "Admission round deadline passed"
    db_session.commit()

    # 1. Attempt commit without reason code -> 409 Conflict
    res_no_reason = client.post(
        f"/api/submissions/{sub_id}/commit",
        headers={"Authorization": f"Bearer {token_a}"},
        json={},
    )
    assert res_no_reason.status_code == 409
    assert "LOCKED" in res_no_reason.json()["message"]

    # 2. Commit with valid late reason code -> Succeeds
    res_late = client.post(
        f"/api/submissions/{sub_id}/commit",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "reason_code": "OFFICIAL_CORRECTION",
            "explanation": "Special state quota reconciliation post-deadline",
        },
    )
    assert res_late.status_code == 200
    assert res_late.json()["committed"] == 1


# ---------------------------------------------------------------------------
# 8. Report CSV Download Test
# ---------------------------------------------------------------------------

def test_submission_report_csv_download(client, submission_setup):
    """
    GET /api/submissions/{id}/report returns CSV with row outcomes and masked APAAR.
    """
    token_a = submission_setup["token_a"]
    inst_a = submission_setup["inst_a"]

    res_create = client.post(
        "/api/submissions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "institution_id": str(inst_a.id),
            "academic_year": "2024-2025",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "round": "ROUND_1",
            "idempotency_key": "report-csv-key-01",
        },
    )
    sub_id = res_create.json()["id"]

    csv_content = (
        "apaar_id,name,dob,gender,mobile,email,roll_no,programme,branch,campus,shift,academic_year,seat_type,category,nri_flag,oci_flag,fn_flag,admission_date,consent_reference,evidence_ref\n"
        "987654321015,Priya Patel,2005-03-21,FEMALE,9876543210,priya@example.com,R107,ENGINEERING_AND_TECHNOLOGY,COMPUTER_SCIENCE_AND_ENGINEERING,MAIN,FIRST,2024-2025,REGULAR,OPEN,false,false,false,2024-08-01,CONSENT-01,DOC-01\n"
    )
    client.post(
        f"/api/submissions/{sub_id}/upload",
        headers={"Authorization": f"Bearer {token_a}", "Content-Type": "text/csv"},
        content=csv_content.encode("utf-8"),
    )
    client.post(
        f"/api/submissions/{sub_id}/commit",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    res_report = client.get(
        f"/api/submissions/{sub_id}/report",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_report.status_code == 200
    assert res_report.headers["content-type"].startswith("text/csv")
    csv_text = res_report.text
    assert "row_number,apaar_masked,name" in csv_text
    assert "XXXX-XXXX-1015" in csv_text
    assert "COMMITTED" in csv_text
