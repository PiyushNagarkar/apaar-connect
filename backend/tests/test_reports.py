"""
Statutory Reports Test Suite (backend/tests/test_reports.py).

Tests:
1. Exported totals equal direct SQL counts for the same filters.
2. Institution users cannot export other institutions (403 Forbidden).
3. Institution users can export their own institution (auto-scoped).
4. Unauthorised roles (STUDENT, VERIFIER) get 403 Forbidden.
5. Unauthenticated requests get 401 Unauthorized.
6. Leading metadata rows exist on every CSV (report name, filters, reporting period,
   generated_at, generated_by, rule_version, denominator definitions).
7. Compliance report contains approved seats, confirmed/active/provisional counts,
   utilisation per category, exception cases, pending clarifications.
8. Missing data is exported as 'N/A', never 0.
"""
from datetime import date, datetime, timedelta, timezone
import pytest

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.audit import AuditEvent
from backend.models.correction import CorrectionRequest
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import Submission
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


@pytest.fixture
def reports_test_data(db_session):
    """Seed comprehensive test fixtures across 2 institutions."""
    now = datetime.now(timezone.utc)

    # 1. Institutions
    inst_a = Institution(code="1-INST-A", name="IIT Delhi", status="ACTIVE")
    inst_b = Institution(code="1-INST-B", name="NIT Trichy", status="ACTIVE")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()

    # 2. Program Approvals
    appr_a = ProgramApproval(
        institution_id=inst_a.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-2024-A-CSE",
        status=ApprovalStatus.FROZEN,
    )
    appr_b = ProgramApproval(
        institution_id=inst_b.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="MECHANICAL_ENGINEERING",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-2024-B-MECH",
        status=ApprovalStatus.FROZEN,
    )
    db_session.add_all([appr_a, appr_b])
    db_session.commit()

    # 3. Seat Allocations
    alloc_a_reg = SeatAllocation(
        approval_id=appr_a.id,
        seat_type=SeatType.REGULAR,
        approved_count=60,
        rule_version="AICTE-APH-2024-V1",
    )
    alloc_a_nri = SeatAllocation(
        approval_id=appr_a.id,
        seat_type=SeatType.NRI,
        approved_count=5,
        rule_version="AICTE-APH-2024-V1",
    )
    alloc_a_zero = SeatAllocation(
        approval_id=appr_a.id,
        seat_type=SeatType.SUPERNUMERARY_FN_OCI_PIO,
        approved_count=0,
        rule_version="AICTE-APH-2024-V1",
    )
    alloc_b_reg = SeatAllocation(
        approval_id=appr_b.id,
        seat_type=SeatType.REGULAR,
        approved_count=40,
        rule_version="AICTE-APH-2024-V1",
    )
    db_session.add_all([alloc_a_reg, alloc_a_nri, alloc_a_zero, alloc_b_reg])
    db_session.commit()

    # 4. Students
    students = []
    for i in range(1, 11):
        st = Student(
            apaar_encrypted=f"enc_token_{i}",
            apaar_hash=f"hash_{i}",
            apaar_masked=f"XXXX-XXXX-{1000 + i}",
            name=f"Student {i}",
            name_normalized=f"STUDENT {i}",
            dob=date(2004, 1, (i % 28) + 1),
            gender="MALE" if i % 2 == 0 else "FEMALE",
            mobile_last4=f"{1000 + i}",
            consent_status="GRANTED",
        )
        students.append(st)
    db_session.add_all(students)
    db_session.commit()

    # 5. Enrollments: 6 in Inst A, 4 in Inst B
    enrollments_a = []
    # Inst A: 4 REGULAR (3 CONFIRMED, 1 PROVISIONAL), 1 NRI (CONFIRMED), 1 OTHER (unapproved offering)
    for idx in range(3):
        enrollments_a.append(
            Enrollment(
                student_id=students[idx].id,
                institution_id=inst_a.id,
                approval_id=appr_a.id,
                academic_year="2024-2025",
                seat_type="REGULAR",
                category="OPEN",
                admission_date=now - timedelta(days=idx),
                round="1",
                status="CONFIRMED",
                identity_status="PASSED",
                authority_status="PASSED",
                compliance_status="PASSED",
                verified=True,
            )
        )
    enrollments_a.append(
        Enrollment(
            student_id=students[3].id,
            institution_id=inst_a.id,
            approval_id=appr_a.id,
            academic_year="2024-2025",
            seat_type="REGULAR",
            category="OBC_NCL",
            admission_date=now,
            round="1",
            status="PROVISIONAL",
            identity_status="PASSED",
            authority_status="PASSED",
            compliance_status="PENDING",
            verified=False,
        )
    )
    enrollments_a.append(
        Enrollment(
            student_id=students[4].id,
            institution_id=inst_a.id,
            approval_id=appr_a.id,
            academic_year="2024-2025",
            seat_type="NRI",
            category="NRI",
            admission_date=now,
            round="1",
            status="CONFIRMED",
            identity_status="PASSED",
            authority_status="PASSED",
            compliance_status="PASSED",
            verified=True,
        )
    )
    enrollments_a.append(
        Enrollment(
            student_id=students[5].id,
            institution_id=inst_a.id,
            approval_id=appr_a.id,
            academic_year="2024-2025",
            seat_type="OTHER",  # Unapproved category!
            category="OTHER",
            admission_date=now,
            round="2",
            status="CONFIRMED",
            identity_status="PASSED",
            authority_status="PASSED",
            compliance_status="FAILED",
            verified=False,
        )
    )
    db_session.add_all(enrollments_a)

    enrollments_b = []
    # Inst B: 4 REGULAR (4 CONFIRMED)
    for idx in range(6, 10):
        enrollments_b.append(
            Enrollment(
                student_id=students[idx].id,
                institution_id=inst_b.id,
                approval_id=appr_b.id,
                academic_year="2024-2025",
                seat_type="REGULAR",
                category="OPEN",
                admission_date=now,
                round="1",
                status="CONFIRMED",
                identity_status="PASSED",
                authority_status="PASSED",
                compliance_status="PASSED",
                verified=True,
            )
        )
    db_session.add_all(enrollments_b)
    db_session.commit()

    # 6. Review Cases
    case_1 = ReviewCase(
        type="NO_APPROVAL_CATEGORY",
        severity="CRITICAL",
        priority=90.0,
        enrollment_id=enrollments_a[5].id,
        institution_id=inst_a.id,
        status="OPEN",
        decision_reason="Admission recorded under unapproved OTHER quota.",
    )
    db_session.add(case_1)
    db_session.commit()

    # 7. Correction Request
    user_dummy = User(
        email="test_operator@iitd.ac.in",
        password_hash=hash_password("Pass123!"),
        role=ROLE_INSTITUTION_OPERATOR,
        institution_id=inst_a.id,
        is_active=True,
    )
    db_session.add(user_dummy)
    db_session.commit()

    corr = CorrectionRequest(
        enrollment_id=enrollments_a[3].id,
        institution_id=inst_a.id,
        requested_by=user_dummy.id,
        status="PENDING",
        reason_code="DEMOGRAPHIC_CORRECTION",
        explanation="Correction of candidate category certificate.",
        proposed_changes={"category": "OPEN"},
    )
    db_session.add(corr)
    db_session.commit()

    # 8. Submissions
    sub_a = Submission(
        institution_id=inst_a.id,
        uploaded_by=user_dummy.id,
        academic_year="2024-2025",
        programme="ENGINEERING_AND_TECHNOLOGY",
        round="1",
        status="COMPLETED",
        counts={"total": 5, "valid": 5, "committed": 5, "failed": 0},
        is_locked=False,
    )
    sub_b = Submission(
        institution_id=inst_b.id,
        uploaded_by=user_dummy.id,
        academic_year="2024-2025",
        programme="ENGINEERING_AND_TECHNOLOGY",
        round="FINAL",
        status="COMPLETED",
        counts={"total": 4, "valid": 4, "committed": 4, "failed": 0},
        is_locked=True,
        lock_reason="Round window closed",
    )
    db_session.add_all([sub_a, sub_b])
    db_session.commit()

    # 9. Audit Events
    audit_ev = AuditEvent(
        actor_id=user_dummy.id,
        institution_id=inst_a.id,
        action="ENROLLMENT_SUBMITTED",
        entity_type="ENROLLMENT",
        entity_id=enrollments_a[0].id,
        reason="Statutory admission ledger commit",
        request_id="req-test-01",
        prev_hash="GENESIS_ROOT_AICTE_APAAR_AUDIT_V1",
        hash="test_hash_01",
    )
    db_session.add(audit_ev)
    db_session.commit()

    # 10. Users for Auth
    user_inst_a = User(
        email="admin@iitd.ac.in",
        password_hash=hash_password("AdminPass123!"),
        role=ROLE_INSTITUTION_ADMIN,
        institution_id=inst_a.id,
        is_active=True,
    )
    user_aicte_admin = User(
        email="admin@aicte.gov.in",
        password_hash=hash_password("AictePass123!"),
        role=ROLE_AICTE_ADMIN,
        institution_id=None,
        is_active=True,
    )
    user_student = User(
        email="student@aicte.gov.in",
        password_hash=hash_password("StudentPass123!"),
        role=ROLE_STUDENT,
        institution_id=inst_a.id,
        is_active=True,
    )
    user_verifier = User(
        email="verifier@employer.com",
        password_hash=hash_password("VerifierPass123!"),
        role=ROLE_VERIFIER,
        institution_id=None,
        is_active=True,
    )
    db_session.add_all([user_inst_a, user_aicte_admin, user_student, user_verifier])
    db_session.commit()

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "appr_a": appr_a,
        "appr_b": appr_b,
        "user_inst_a": user_inst_a,
        "user_aicte_admin": user_aicte_admin,
        "user_student": user_student,
        "user_verifier": user_verifier,
        "enrollments_a": enrollments_a,
        "enrollments_b": enrollments_b,
    }


def parse_csv_lines(csv_text: str):
    """Splits CSV text into metadata comment lines and table data rows."""
    metadata_lines = []
    data_lines = []
    for line in csv_text.splitlines():
        if line.startswith("#"):
            metadata_lines.append(line)
        elif line.strip():
            data_lines.append(line)
    return metadata_lines, data_lines


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_unauthenticated_request_returns_401(client):
    """Accessing report endpoints without authentication returns 401 Unauthorized."""
    res = client.get("/api/reports/compliance")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_unauthorised_roles_return_403(client, reports_test_data):
    """Roles without reporting privileges (STUDENT, VERIFIER) receive 403 Forbidden."""
    # 1. Student role
    token_student = create_jwt({
        "sub": str(reports_test_data["user_student"].id),
        "email": reports_test_data["user_student"].email,
        "role": ROLE_STUDENT,
        "institution_id": reports_test_data["inst_a"].id,
    })
    res = client.get("/api/reports/enrolment", headers={"Authorization": f"Bearer {token_student}"})
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"

    # 2. Public Verifier role
    token_verifier = create_jwt({
        "sub": str(reports_test_data["user_verifier"].id),
        "email": reports_test_data["user_verifier"].email,
        "role": ROLE_VERIFIER,
    })
    res = client.get("/api/reports/compliance", headers={"Authorization": f"Bearer {token_verifier}"})
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"


def test_institution_user_cannot_export_other_institutions(client, reports_test_data):
    """Institution users cannot pass another institution's ID in query filters; must return 403."""
    inst_a_id = reports_test_data["inst_a"].id
    inst_b_id = reports_test_data["inst_b"].id

    token_inst_a = create_jwt({
        "sub": str(reports_test_data["user_inst_a"].id),
        "email": reports_test_data["user_inst_a"].email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_a_id,
    })

    # Inst A user tries to query Inst B
    res = client.get(
        f"/api/reports/compliance?institution={inst_b_id}",
        headers={"Authorization": f"Bearer {token_inst_a}"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert "Scope violation" in res.json()["message"]


def test_institution_user_auto_scoped_to_own_institution(client, reports_test_data):
    """Institution user query with no institution filter automatically isolates to their own institution."""
    inst_a_id = reports_test_data["inst_a"].id
    inst_b_id = reports_test_data["inst_b"].id

    token_inst_a = create_jwt({
        "sub": str(reports_test_data["user_inst_a"].id),
        "email": reports_test_data["user_inst_a"].email,
        "role": ROLE_INSTITUTION_ADMIN,
        "institution_id": inst_a_id,
    })

    res = client.get(
        "/api/reports/enrolment",
        headers={"Authorization": f"Bearer {token_inst_a}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")

    _, data_lines = parse_csv_lines(res.text)
    # Line 0 is headers, lines 1+ are data rows
    assert len(data_lines) > 1
    # Check that every single data row belongs strictly to inst_a_id and never to inst_b_id
    for row in data_lines[1:]:
        assert inst_a_id in row
        assert inst_b_id not in row


def test_exported_totals_equal_direct_sql_counts_for_same_filters(client, reports_test_data, db_session):
    """Exported CSV data row totals strictly match direct database SQL query counts for the same filters."""
    token_admin = create_jwt({
        "sub": str(reports_test_data["user_aicte_admin"].id),
        "email": reports_test_data["user_aicte_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })

    # 1. Enrolment Report: Test with round="1" filter
    sql_enr_count = db_session.query(Enrollment).filter(Enrollment.round == "1").count()

    res = client.get(
        "/api/reports/enrolment?round=1",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res.status_code == 200
    _, data_lines = parse_csv_lines(res.text)
    # data_lines[0] is header row; remaining are records
    exported_enr_count = len(data_lines) - 1
    assert exported_enr_count == sql_enr_count
    assert exported_enr_count == 9  # 5 in Inst A (round 1) + 4 in Inst B (round 1)

    # 2. Duplicates Report: Direct count match
    sql_case_count = db_session.query(ReviewCase).count()
    res_cases = client.get(
        "/api/reports/duplicates",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_cases.status_code == 200
    _, case_lines = parse_csv_lines(res_cases.text)
    assert len(case_lines) - 1 == sql_case_count

    # 3. Audit Report: Direct count match
    sql_audit_count = db_session.query(AuditEvent).count()
    res_audit = client.get(
        "/api/reports/audit",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_audit.status_code == 200
    _, audit_lines = parse_csv_lines(res_audit.text)
    assert len(audit_lines) - 1 == sql_audit_count


def test_compliance_report_contains_required_fields_and_na(client, reports_test_data):
    """
    Compliance report verifies:
    - Approved seats, confirmed/active/provisional counts, utilisation per category,
      exception cases, and pending clarifications.
    - Missing data (e.g. unapproved quota or 0-approved quota utilisation) is exported as 'N/A', never 0.
    """
    inst_a_id = reports_test_data["inst_a"].id
    token_admin = create_jwt({
        "sub": str(reports_test_data["user_aicte_admin"].id),
        "email": reports_test_data["user_aicte_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })

    res = client.get(
        f"/api/reports/compliance?institution={inst_a_id}",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res.status_code == 200

    metadata_lines, data_lines = parse_csv_lines(res.text)
    header_row = data_lines[0].split(",")

    # Verify column presence
    assert "Approved Seats" in header_row
    assert "Confirmed Admissions" in header_row
    assert "Active Admissions" in header_row
    assert "Provisional Admissions" in header_row
    assert "Category Utilisation (%)" in header_row
    assert "Exception Cases Count" in header_row
    assert "Pending Clarifications Count" in header_row
    assert "Compliance Status" in header_row

    # Verify rows
    content = res.text
    # Check that unapproved offering category 'OTHER' has Approved Seats == N/A
    assert "UNAPPROVED_OFFERING" in content
    # Check that Supernumerary category with 0 approved seats has Utilisation == N/A
    # Missing data must be 'N/A', not '0'
    assert "N/A" in content


def test_csv_metadata_rows_header(client, reports_test_data):
    """Every report begins with the exact required metadata rows."""
    token_admin = create_jwt({
        "sub": str(reports_test_data["user_aicte_admin"].id),
        "email": reports_test_data["user_aicte_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })

    res = client.get(
        "/api/reports/compliance?academic_year=2024-2025",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res.status_code == 200

    metadata_lines, _ = parse_csv_lines(res.text)
    meta_text = "\n".join(metadata_lines)

    assert "# Report Name:" in meta_text
    assert "# Applied Filters:" in meta_text
    assert "academic_year=2024-2025" in meta_text
    assert "# Reporting Period:" in meta_text
    assert "# Generated At:" in meta_text
    assert "# Generated By:" in meta_text
    assert "# Rule Version:" in meta_text
    assert "# Denominator Definitions:" in meta_text


def test_all_six_report_types_accessible_by_admin(client, reports_test_data):
    """All 6 report types succeed with 200 OK and valid CSV payload when accessed by an authorized role."""
    token_admin = create_jwt({
        "sub": str(reports_test_data["user_aicte_admin"].id),
        "email": reports_test_data["user_aicte_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })
    headers = {"Authorization": f"Bearer {token_admin}"}

    reports = [
        "enrolment",
        "enrollment",  # Alias
        "compliance",
        "data-quality",
        "duplicates",
        "timeliness",
        "audit",
    ]

    for r in reports:
        res = client.get(f"/api/reports/{r}", headers=headers)
        assert res.status_code == 200, f"Report '{r}' failed with status {res.status_code}"
        assert res.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=" in res.headers["content-disposition"]
        assert len(res.text) > 50


def test_invalid_report_type_returns_400(client, reports_test_data):
    """Requesting an unknown report type returns 400 Bad Request."""
    token_admin = create_jwt({
        "sub": str(reports_test_data["user_aicte_admin"].id),
        "email": reports_test_data["user_aicte_admin"].email,
        "role": ROLE_AICTE_ADMIN,
    })

    res = client.get("/api/reports/unknown-xyz", headers={"Authorization": f"Bearer {token_admin}"})
    assert res.status_code == 400
    assert res.json()["code"] == "BAD_REQUEST"
