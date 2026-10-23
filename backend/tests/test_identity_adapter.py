from datetime import date, datetime, timedelta, timezone
import pytest

from backend.models.institution import Institution
from backend.models.student import Student
from backend.models.identity import IdentityCheck
from backend.security.crypto import create_jwt
from backend.services.identity_adapter import (
    MockApaarProvider,
    get_identity_provider,
    verify_with_retry,
    evaluate_identity_policy,
    generate_valid_apaar,
    validate_apaar_format_and_checksum,
    normalize_name,
    check_name_similarity,
    STATUS_PASSED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_UNAVAILABLE,
    STATUS_NOT_PROVIDED,
    REASON_MATCH_CONFIRMED,
    REASON_NOT_PROVIDED,
    REASON_FORMAT,
    REASON_NOT_FOUND,
    REASON_MISMATCH,
    REASON_TIMEOUT,
    REASON_PENDING,
)


@pytest.fixture
def identity_fixture(db_session):
    """Seed test institution and student for identity verification endpoints."""
    inst = Institution(code="1-ID-TEST", name="Test Engineering College", status="ACTIVE")
    db_session.add(inst)
    db_session.commit()

    student = Student(
        apaar_encrypted="enc_tok",
        apaar_hash="hash_priya",
        apaar_masked="XXXX-XXXX-1015",
        name="Priya Patel",
        name_normalized="PRIYA PATEL",
        dob=date(2005, 3, 21),
        gender="FEMALE",
        consent_status="GRANTED",
    )
    db_session.add(student)
    db_session.commit()

    token = create_jwt({"sub": "admin-01", "email": "admin@aicte.gov.in", "role": "AICTE_ADMIN"})

    return {
        "inst": inst,
        "student": student,
        "token": token,
    }


# ---------------------------------------------------------------------------
# Unit Tests for Each Status Path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_path_passed():
    """Test PASSED: Valid APAAR in registry, matching name and DOB."""
    provider = MockApaarProvider()
    res = await provider.verify(
        request_id="req-pass-01",
        apaar_id="987654321015",
        student_name="Priya  Patel",  # Extra whitespace to test normalization
        date_of_birth="2005-03-21",
    )
    assert res.status == STATUS_PASSED
    assert res.source == "MOCK_APAAR_V1"
    assert res.exists is True
    assert res.name_match is True
    assert res.dob_match is True
    assert res.reason_code == REASON_MATCH_CONFIRMED


@pytest.mark.asyncio
async def test_status_path_not_provided():
    """Test NOT_PROVIDED: APAAR is None or empty. Unchecked fields must be null."""
    provider = MockApaarProvider()
    res = await provider.verify(
        request_id="req-not-provided",
        apaar_id=None,
        student_name="Aarav Sharma",
        date_of_birth="2004-05-14",
    )
    assert res.status == STATUS_NOT_PROVIDED
    assert res.source == "MOCK_APAAR_V1"
    assert res.exists is None
    assert res.name_match is None
    assert res.dob_match is None
    assert res.reason_code == REASON_NOT_PROVIDED


@pytest.mark.asyncio
async def test_status_path_failed_format():
    """Test FAILED(FORMAT): Bad checksum or invalid digit length. Unchecked fields must be null."""
    provider = MockApaarProvider()
    # Invalid length (less than 12 digits)
    res_short = await provider.verify(
        request_id="req-fmt-short",
        apaar_id="12345",
        student_name="Aarav Sharma",
        date_of_birth="2004-05-14",
    )
    assert res_short.status == STATUS_FAILED
    assert res_short.exists is False
    assert res_short.name_match is None
    assert res_short.dob_match is None
    assert res_short.reason_code == REASON_FORMAT

    # 12 digits but invalid Luhn checksum
    res_bad_chk = await provider.verify(
        request_id="req-fmt-chk",
        apaar_id="123456789019",  # Deliberately wrong check digit
        student_name="Aarav Sharma",
        date_of_birth="2004-05-14",
    )
    assert res_bad_chk.status == STATUS_FAILED
    assert res_bad_chk.exists is False
    assert res_bad_chk.name_match is None
    assert res_bad_chk.dob_match is None
    assert res_bad_chk.reason_code == REASON_FORMAT


@pytest.mark.asyncio
async def test_status_path_failed_not_found():
    """Test FAILED(NOT_FOUND): Mathematically valid APAAR but not in synthetic registry."""
    provider = MockApaarProvider()
    # Construct a valid Luhn 12-digit number that is not registered
    valid_unregistered = generate_valid_apaar("33333333333")
    res = await provider.verify(
        request_id="req-not-found",
        apaar_id=valid_unregistered,
        student_name="Unknown Student",
        date_of_birth="2000-01-01",
    )
    assert res.status == STATUS_FAILED
    assert res.exists is False
    assert res.name_match is None
    assert res.dob_match is None
    assert res.reason_code == REASON_NOT_FOUND


@pytest.mark.asyncio
async def test_status_path_failed_mismatch():
    """Test FAILED(MISMATCH): In registry, but name or DOB mismatch with per-field booleans."""
    provider = MockApaarProvider()
    # Correct DOB, wrong name
    res_name_mismatch = await provider.verify(
        request_id="req-mis-name",
        apaar_id="987654321015",
        student_name="Siddharth Malhotra",  # Registry has "Priya Patel"
        date_of_birth="2005-03-21",
    )
    assert res_name_mismatch.status == STATUS_FAILED
    assert res_name_mismatch.exists is True
    assert res_name_mismatch.name_match is False
    assert res_name_mismatch.dob_match is True
    assert res_name_mismatch.reason_code == REASON_MISMATCH

    # Correct name, wrong DOB
    res_dob_mismatch = await provider.verify(
        request_id="req-mis-dob",
        apaar_id="987654321015",
        student_name="Priya Patel",
        date_of_birth="1999-12-31",  # Registry has "2005-03-21"
    )
    assert res_dob_mismatch.status == STATUS_FAILED
    assert res_dob_mismatch.exists is True
    assert res_dob_mismatch.name_match is True
    assert res_dob_mismatch.dob_match is False
    assert res_dob_mismatch.reason_code == REASON_MISMATCH


@pytest.mark.asyncio
async def test_status_path_pending():
    """Test PENDING: Special magic ID ending with '888' simulates asynchronous processing."""
    provider = MockApaarProvider()
    res = await provider.verify(
        request_id="req-pending",
        apaar_id="987654321888",
        student_name="Any Name",
        date_of_birth="2004-01-01",
    )
    assert res.status == STATUS_PENDING
    assert res.exists is None
    assert res.reason_code == REASON_PENDING


@pytest.mark.asyncio
async def test_status_path_unavailable_timeout():
    """Test UNAVAILABLE: Special magic ID ending with '999' simulates downstream timeout."""
    provider = MockApaarProvider()
    res = await provider.verify(
        request_id="req-timeout",
        apaar_id="987654321999",
        student_name="Any Name",
        date_of_birth="2004-01-01",
    )
    assert res.status == STATUS_UNAVAILABLE
    assert res.exists is None
    assert res.reason_code == REASON_TIMEOUT


# ---------------------------------------------------------------------------
# Policy Engine & Unavailable Guarantee Tests
# ---------------------------------------------------------------------------

def test_unavailable_keeps_record_provisional():
    """
    Test rule: UNAVAILABLE never marks the record failed or verified.
    Must always stay PROVISIONAL.
    """
    policy = evaluate_identity_policy(STATUS_UNAVAILABLE)
    assert policy["lifecycle_status"] == "PROVISIONAL"
    assert policy["is_compliant"] is True
    assert policy["escalated_error"] is False
    assert policy["identity_resolution"] == "RETRY_QUEUED"


def test_grace_period_expiry_policy():
    """
    Test policy engine:
    - NOT_PROVIDED within grace period (<= 30 days) stays PROVISIONAL.
    - NOT_PROVIDED past grace period (> 30 days) escalates to ERROR.
    """
    now = datetime.now(timezone.utc)

    # 1. Within grace period: 10 days since admission
    admit_recent = now - timedelta(days=10)
    policy_active = evaluate_identity_policy(
        STATUS_NOT_PROVIDED,
        admission_date=admit_recent,
        grace_period_days=30,
    )
    assert policy_active["lifecycle_status"] == "PROVISIONAL"
    assert policy_active["is_compliant"] is True
    assert policy_active["escalated_error"] is False
    assert policy_active["grace_days_remaining"] == 20

    # 2. Past grace period: 35 days since admission
    admit_old = now - timedelta(days=35)
    policy_expired = evaluate_identity_policy(
        STATUS_NOT_PROVIDED,
        admission_date=admit_old,
        grace_period_days=30,
    )
    assert policy_expired["lifecycle_status"] == "ERROR"
    assert policy_expired["is_compliant"] is False
    assert policy_expired["escalated_error"] is True
    assert policy_expired["grace_days_remaining"] == 0
    assert "grace period expired" in policy_expired["reason"]


@pytest.mark.asyncio
async def test_verify_with_retry_exponential_backoff():
    """Test retry simulator with exponential backoff on UNAVAILABLE."""
    provider = MockApaarProvider()
    # ID ending in 999 triggers UNAVAILABLE
    result, attempts = await verify_with_retry(
        provider=provider,
        request_id="req-retry-test",
        apaar_id="987654321999",
        student_name="Test Student",
        date_of_birth="2005-01-01",
        max_retries=3,
        initial_delay=0.01,
        backoff_multiplier=1.5,
    )
    assert attempts == 3
    assert result.status == STATUS_UNAVAILABLE
    # Still PROVISIONAL per policy
    policy = evaluate_identity_policy(result.status)
    assert policy["lifecycle_status"] == "PROVISIONAL"


def test_name_similarity_matching():
    """Test name normalization and similarity matching."""
    # Extra whitespace and casing
    assert check_name_similarity("Aarav  Sharma", "AARAV SHARMA") is True
    # Honorifics
    assert check_name_similarity("Mr. Aarav Sharma", "AARAV SHARMA") is True
    # Token reordering
    assert check_name_similarity("Sharma, Aarav", "Aarav Sharma") is True
    # Completely different name
    assert check_name_similarity("Aarav Sharma", "Vikram Singh") is False


# ---------------------------------------------------------------------------
# API Endpoints Integration Tests
# ---------------------------------------------------------------------------

def test_api_post_verify_and_persistence(client, identity_fixture, db_session):
    """Test POST /api/identity/verify persists to identity_checks and never logs full APAAR."""
    student = identity_fixture["student"]
    token = identity_fixture["token"]

    response = client.post(
        "/api/identity/verify",
        json={
            "student_id": str(student.id),
            "apaar_id": "987654321015",
            "student_name": "Priya Patel",
            "date_of_birth": "2005-03-21",
            "consent_reference": "CONSENT-API-001",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PASSED"
    assert data["source"] == "MOCK_APAAR_V1"
    assert data["exists"] is True
    assert data["name_match"] is True
    assert data["dob_match"] is True
    check_id = data["check_id"]

    # Verify database persistence
    check_db = db_session.query(IdentityCheck).filter(IdentityCheck.id == check_id).first()
    assert check_db is not None
    assert check_db.status == "PASSED"
    # Never log full APAAR ID: raw JSON must contain masked APAAR
    assert check_db.raw["apaar_masked"] == "XXXX-XXXX-1015"
    assert "987654321015" not in check_db.raw.get("apaar_masked", "")


def test_api_get_identity_check_by_id(client, identity_fixture):
    """Test GET /api/identity/checks/{id} returns saved check."""
    student = identity_fixture["student"]

    # Create check via POST
    res_post = client.post(
        "/api/identity/verify",
        json={
            "student_id": str(student.id),
            "apaar_id": "987654321015",
            "student_name": "Priya Patel",
            "date_of_birth": "2005-03-21",
        },
    )
    check_id = res_post.json()["check_id"]

    # Fetch check via GET
    res_get = client.get(f"/api/identity/checks/{check_id}")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["check_id"] == check_id
    assert data["status"] == "PASSED"
    assert data["source"] == "MOCK_APAAR_V1"


def test_api_get_student_identity_checks(client, identity_fixture):
    """Test GET /api/students/{id}/identity-checks returns list of checks."""
    student = identity_fixture["student"]
    token = identity_fixture["token"]
    student_id = str(student.id)

    # Perform two checks for the student
    client.post(
        "/api/identity/verify",
        json={"student_id": student_id, "apaar_id": "987654321015", "student_name": "Priya Patel", "date_of_birth": "2005-03-21"},
    )
    client.post(
        "/api/identity/verify",
        json={"student_id": student_id, "apaar_id": None, "student_name": "Priya Patel", "date_of_birth": "2005-03-21"},
    )

    # Query checks for this student
    res = client.get(
        f"/api/students/{student_id}/identity-checks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == student_id
    assert data["total_checks"] >= 2
    statuses = [c["status"] for c in data["checks"]]
    assert "PASSED" in statuses
    assert "NOT_PROVIDED" in statuses
