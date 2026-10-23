from datetime import date, datetime, timedelta, timezone
import pytest
from jose import jwt

from backend.models.institution import Institution
from backend.models.user import User
from backend.models.student import Student
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.enrollment import Enrollment
from backend.models.audit import AuditEvent
from backend.security.crypto import hash_password, create_jwt, SECRET_KEY
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
)
from backend.security.masking import mask_student_for_role


@pytest.fixture
def test_setup_data(db_session):
    """Seed test fixtures: 2 institutions, approvals, enrollments, students, and users."""
    now = datetime.now(timezone.utc)

    # Institutions A & B
    inst_a = Institution(code="1-INST-A", name="IIT Delhi", status="ACTIVE")
    inst_b = Institution(code="1-INST-B", name="NIT Trichy", status="ACTIVE")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()

    # Approvals for Inst A & B
    appr_a = ProgramApproval(
        institution_id=inst_a.id, programme="ENG", branch="CSE",
        academic_year="2024-2025", approval_ref="EOA-A-001", status=ApprovalStatus.FROZEN
    )
    appr_b = ProgramApproval(
        institution_id=inst_b.id, programme="ENG", branch="CSE",
        academic_year="2024-2025", approval_ref="EOA-B-001", status=ApprovalStatus.FROZEN
    )
    db_session.add_all([appr_a, appr_b])
    db_session.commit()

    # Students 1 & 2
    student_1 = Student(
        apaar_encrypted="enc_token_1", apaar_hash="hash_student_1", apaar_masked="XXXX-XXXX-1001",
        name="Aarav Sharma", name_normalized="AARAV SHARMA", dob=date(2005, 1, 1), gender="MALE",
        mobile_last4="1001", consent_status="GRANTED"
    )
    student_2 = Student(
        apaar_encrypted="enc_token_2", apaar_hash="hash_student_2", apaar_masked="XXXX-XXXX-2002",
        name="Bhavna Rao", name_normalized="BHAVNA RAO", dob=date(2005, 2, 2), gender="FEMALE",
        mobile_last4="2002", consent_status="GRANTED"
    )
    db_session.add_all([student_1, student_2])
    db_session.commit()

    # Enrollments for Inst A & B
    enrollment_a = Enrollment(
        student_id=student_1.id, institution_id=inst_a.id, approval_id=appr_a.id,
        academic_year="2024-2025", seat_type="REGULAR", category="OPEN", admission_date=now
    )
    enrollment_b = Enrollment(
        student_id=student_2.id, institution_id=inst_b.id, approval_id=appr_b.id,
        academic_year="2024-2025", seat_type="REGULAR", category="OPEN", admission_date=now
    )
    db_session.add_all([enrollment_a, enrollment_b])
    db_session.commit()

    # Demo users
    user_op_a = User(
        email="operator.a@iitd.ac.in",
        password_hash=hash_password("OperatorPass123!"),
        role=ROLE_INSTITUTION_OPERATOR,
        institution_id=inst_a.id,
        is_active=True,
    )
    user_student = User(
        email="aarav@student.gov.in",
        password_hash=hash_password("StudentPass123!"),
        role=ROLE_STUDENT,
        institution_id=inst_a.id,
        is_active=True,
    )
    user_auditor = User(
        email="auditor@cag.gov.in",
        password_hash=hash_password("AuditorPass123!"),
        role=ROLE_AUDITOR,
        institution_id=None,
        is_active=True,
    )
    db_session.add_all([user_op_a, user_student, user_auditor])
    db_session.commit()

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "enrollment_a": enrollment_a,
        "enrollment_b": enrollment_b,
        "student_1": student_1,
        "student_2": student_2,
        "user_op_a": user_op_a,
        "user_student": user_student,
        "user_auditor": user_auditor,
        "appr_a": appr_a,
    }


def test_operator_institution_a_requests_enrollment_of_institution_b_returns_403(client, test_setup_data):
    """
    Acceptance check 1:
    Operator of institution A requests an enrollment of institution B -> 404 or 403.
    """
    token_op_a = create_jwt({
        "sub": str(test_setup_data["user_op_a"].id),
        "email": test_setup_data["user_op_a"].email,
        "role": ROLE_INSTITUTION_OPERATOR,
        "institution_id": str(test_setup_data["inst_a"].id),
    })

    # Operator A requests enrollment belonging to Institution B
    enrollment_b_id = str(test_setup_data["enrollment_b"].id)
    response = client.get(
        f"/api/enrollments/{enrollment_b_id}",
        headers={"Authorization": f"Bearer {token_op_a}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert "Scope violation" in response.json()["message"]


def test_student_requests_another_student_returns_403(client, test_setup_data):
    """
    Acceptance check 2:
    Student requests another student -> 403.
    """
    # Student 1 authenticated token
    token_student_1 = create_jwt({
        "sub": str(test_setup_data["user_student"].id),
        "email": test_setup_data["user_student"].email,
        "role": ROLE_STUDENT,
        "student_id": str(test_setup_data["student_1"].id),
    })

    # Student 1 attempts to view Student 2
    student_2_id = str(test_setup_data["student_2"].id)
    response = client.get(
        f"/api/students/{student_2_id}",
        headers={"Authorization": f"Bearer {token_student_1}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert "Students are permitted to view only their own records" in response.json()["message"]


def test_student_requests_own_record_succeeds_with_masking(client, test_setup_data):
    """Student requesting own record succeeds and receives masked APAAR, never ciphertext."""
    token_student_1 = create_jwt({
        "sub": str(test_setup_data["user_student"].id),
        "email": test_setup_data["user_student"].email,
        "role": ROLE_STUDENT,
        "student_id": str(test_setup_data["student_1"].id),
    })

    student_1_id = str(test_setup_data["student_1"].id)
    response = client.get(
        f"/api/students/{student_1_id}",
        headers={"Authorization": f"Bearer {token_student_1}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Aarav Sharma"
    assert data["apaar_masked"] == "XXXX-XXXX-1001"
    assert "apaar_encrypted" not in data


def test_auditor_attempts_write_returns_403(client, test_setup_data):
    """
    Acceptance check 3:
    Auditor attempts a write -> 403.
    """
    token_auditor = create_jwt({
        "sub": str(test_setup_data["user_auditor"].id),
        "email": test_setup_data["user_auditor"].email,
        "role": ROLE_AUDITOR,
    })

    # Auditor attempts to create an enrollment
    response = client.post(
        "/api/enrollments",
        headers={"Authorization": f"Bearer {token_auditor}"},
        json={
            "student_id": str(test_setup_data["student_1"].id),
            "approval_id": str(test_setup_data["appr_a"].id),
            "academic_year": "2024-2025",
            "seat_type": "REGULAR",
            "category": "OPEN",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert "lacks permission for action" in response.json()["message"]


def test_expired_token_returns_401(client, test_setup_data):
    """
    Acceptance check 4:
    Expired token -> 401.
    """
    # Create token expired 10 minutes ago
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired_payload = {
        "sub": "user-expired",
        "email": "expired@aicte.gov.in",
        "role": ROLE_AICTE_ADMIN,
        "exp": past,
        "iat": past - timedelta(minutes=15),
    }
    expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm="HS256")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


def test_login_success_and_httponly_cookie(client, test_setup_data):
    """Test successful login issues token and sets HttpOnly cookie."""
    response = client.post(
        "/api/auth/login",
        json={"email": "operator.a@iitd.ac.in", "password": "OperatorPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "operator.a@iitd.ac.in"
    # HttpOnly cookie check
    assert "access_token" in response.cookies


def test_login_failure_logs_audit_event(client, db_session, test_setup_data):
    """Test failed login returns 401 and writes audit event."""
    response = client.post(
        "/api/auth/login",
        json={"email": "operator.a@iitd.ac.in", "password": "WrongPassword999!"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"

    # Verify audit event logged
    audit = db_session.query(AuditEvent).filter(
        AuditEvent.action == "AUTH_LOGIN_FAILED",
        AuditEvent.actor_id == "operator.a@iitd.ac.in"
    ).first()
    assert audit is not None


def test_field_level_masking_helper():
    """Test field-level masking helper across different roles."""
    student_dict = {
        "id": "std-001",
        "name": "Priya Patel",
        "name_normalized": "PRIYA PATEL",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "apaar_masked": "XXXX-XXXX-9999",
        "apaar_hash": "hash_xyz_blind_index",
        "mobile_last4": "9999",
        "consent_status": "GRANTED",
        "created_at": "2024-01-01T00:00:00Z",
    }

    # Auditor view: pseudonymized name & year only DOB
    auditor_view = mask_student_for_role(student_dict, ROLE_AUDITOR)
    assert "P****" in auditor_view["name"]
    assert auditor_view["dob"] == "2005-XX-XX"
    assert auditor_view["apaar_masked"] == "XXXX-XXXX-9999"

    # Institution view: full name, DOB, masked APAAR
    inst_view = mask_student_for_role(student_dict, ROLE_INSTITUTION_OPERATOR)
    assert inst_view["name"] == "Priya Patel"
    assert inst_view["dob"] == "2005-03-21"
    assert inst_view["apaar_masked"] == "XXXX-XXXX-9999"
