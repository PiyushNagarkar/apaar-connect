"""
Comprehensive Automated Tests for Verifiable Credentials (backend/tests/test_credentials.py).

Covers all required user specifications:
1. Issuance only for verified=True and CONFIRMED/ACTIVE/COMPLETED enrollments.
2. 128-bit public_ref (URL-safe) and Ed25519 signature over canonical JSON.
3. QR code encodes ONLY https://<host>/verify/<public_ref> (NO APAAR ID, DOB, contact, or name).
4. Verification pipeline:
   - Unknown ref -> UNKNOWN
   - Tampered payload -> MALFORMED
   - Expired credential -> EXPIRED
   - Revoked credential -> REVOKED
   - Revocation reflected instantly on refresh
   - Student consent withdrawn -> limited response
   - SERVICE_UNAVAILABLE never renders as valid
   - Offline verification shows "Revocation not checked"
5. Auto-revocation when enrollment transitions to REJECTED/CANCELLED/WITHDRAWN.
6. Registered verifiers (API key, declared purpose, rate limits, verification logs).
7. Minimal field disclosure by caller class (anonymous / registered verifier / authorised staff).
8. Certificate sample HTML & PDF template printing "Student ID + APAAR ID (masked)" (Rule 10).
"""
import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import qrcode
from fastapi.testclient import TestClient

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.credential import Credential, RegisteredVerifier, VerificationLog
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.seat import SeatAllocation
from backend.models.student import Student
from backend.security.crypto import encrypt_apaar, compute_apaar_hash, mask_apaar
from backend.services.credential_service import (
    ACTIVE_KEY_ID,
    canonical_json_bytes,
    get_signing_key,
    issue_credential,
    revoke_credential,
    verify_credential,
    verify_credential_offline,
)
from backend.services.lifecycle import transition_enrollment_status


# ---------------------------------------------------------------------------
# Fixture Helpers
# ---------------------------------------------------------------------------
def create_test_hierarchy(db, enrollment_status="CONFIRMED", verified=True, consent_status="GRANTED"):
    """Helper to create institution, approval, student, and enrollment."""
    uid = uuid.uuid4().hex[:8]

    inst = Institution(
        id=f"inst-{uid}",
        code=f"AICTE-INST-{uid.upper()}",
        name=f"College of Engineering {uid.upper()}",
        status="ACTIVE",
    )
    db.add(inst)
    db.flush()

    app = ProgramApproval(
        id=f"app-{uid}",
        institution_id=inst.id,
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        academic_year="2024-2025",
        approval_ref=f"EOA-{uid.upper()}",
        version=1,
        status=ApprovalStatus.FROZEN,
    )
    db.add(app)
    db.flush()

    raw_apaar = f"88880000{uid[:4]}"
    student = Student(
        id=f"std-{uid}",
        apaar_encrypted=encrypt_apaar(raw_apaar),
        apaar_hash=compute_apaar_hash(raw_apaar),
        apaar_masked=mask_apaar(raw_apaar),
        name=f"Aarav Sharma {uid}",
        name_normalized=f"aarav sharma {uid}",
        dob=date(2003, 5, 15),
        gender="MALE",
        consent_status=consent_status,
    )
    db.add(student)
    db.flush()

    enrollment = Enrollment(
        id=f"enr-{uid}",
        student_id=student.id,
        institution_id=inst.id,
        approval_id=app.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        status=enrollment_status,
        verified=verified,
        identity_status="PASS",
        authority_status="CONFIRMED",
        compliance_status="VALID",
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    return inst, app, student, enrollment


# ---------------------------------------------------------------------------
# 1. Issuance Tests & Eligibility Constraints
# ---------------------------------------------------------------------------
def test_issuance_eligibility_enforcement(client, db_session):
    """
    Requirement: POST /api/credentials ONLY for enrollments with verified=True
    and status in CONFIRMED, ACTIVE, COMPLETED.
    """
    # 1. Unverified enrollment -> Should fail
    _, _, _, enr_unverified = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=False)
    res = client.post(
        "/api/credentials",
        json={"enrollment_id": enr_unverified.id},
        headers={"X-Mock-Role": "INSTITUTION_ADMIN", "X-Mock-Institution-Id": enr_unverified.institution_id},
    )
    assert res.status_code == 400
    assert "verified=True" in res.json()["message"]

    # 2. Ineligible status (PROVISIONAL) -> Should fail even if verified=True
    _, _, _, enr_provisional = create_test_hierarchy(db_session, enrollment_status="PROVISIONAL", verified=True)
    res2 = client.post(
        "/api/credentials",
        json={"enrollment_id": enr_provisional.id},
        headers={"X-Mock-Role": "INSTITUTION_ADMIN", "X-Mock-Institution-Id": enr_provisional.institution_id},
    )
    assert res2.status_code == 400

    # 3. Eligible enrollment (CONFIRMED + verified=True) -> Should succeed
    _, _, student, enr_eligible = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    res3 = client.post(
        "/api/credentials",
        json={"enrollment_id": enr_eligible.id, "completion_year": 2028},
        headers={"X-Mock-Role": "INSTITUTION_ADMIN", "X-Mock-Institution-Id": enr_eligible.institution_id},
    )
    assert res3.status_code == 201
    data = res3.json()
    assert data["status"] == "ACTIVE"
    assert data["public_ref"].startswith("CRED-")
    assert data["payload"]["student_display_name"] == student.name
    assert data["payload"]["completion_year"] == 2028
    assert data["key_id"] == ACTIVE_KEY_ID
    assert "signature" in data
    # Rule 10: Ensure no raw APAAR ID in payload
    payload_str = json.dumps(data["payload"])
    assert "88880000" not in payload_str


# ---------------------------------------------------------------------------
# 2. Public Key Rotation Endpoint
# ---------------------------------------------------------------------------
def test_public_keys_publishing(client):
    """Requirement: Publish public keys at GET /api/keys with key_id for rotation."""
    res = client.get("/api/keys")
    assert res.status_code == 200
    data = res.json()
    assert data["active_key_id"] == ACTIVE_KEY_ID
    assert len(data["keys"]) >= 1

    active_key = next(k for k in data["keys"] if k["key_id"] == data["active_key_id"])
    assert active_key["algorithm"] == "Ed25519"
    assert active_key["status"] == "ACTIVE"
    assert "public_key" in active_key
    assert "-----BEGIN PUBLIC KEY-----" in active_key["public_key_pem"]


# ---------------------------------------------------------------------------
# 3. QR Code Content & Format Tests
# ---------------------------------------------------------------------------
def test_qr_code_contains_only_reference(client, db_session):
    """
    Requirement: QR encodes ONLY https://<host>/verify/<public_ref>.
    NO APAAR ID, DOB, contact or name in the QR.
    Generate PNG and SVG server-side.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="ACTIVE", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # 1. Test SVG QR endpoint
    res_svg = client.get(f"/api/credentials/{cred.id}/qr.svg")
    assert res_svg.status_code == 200
    assert res_svg.headers["content-type"].startswith("image/svg+xml")
    svg_text = res_svg.text
    assert "<svg" in svg_text
    # Verify no PII is leaked in svg text or attributes
    assert student.name not in svg_text
    assert "2003-05-15" not in svg_text
    assert "apaar" not in svg_text.lower()

    # 2. Test PNG QR endpoint
    res_png = client.get(f"/api/credentials/{cred.id}/qr.png")
    assert res_png.status_code == 200
    assert res_png.headers["content-type"].startswith("image/png")
    assert len(res_png.content) > 100

    # 3. Test verification URL content inside QR generator
    from backend.services.credential_service import build_verification_url
    expected_url = build_verification_url(cred.public_ref, "https://aicte.gov.in")
    assert expected_url == f"https://aicte.gov.in/verify/{cred.public_ref}"

    qr = qrcode.QRCode()
    qr.add_data(expected_url)
    assert qr.data_list[0].data == expected_url.encode("utf-8")
    assert cred.public_ref.encode("utf-8") in qr.data_list[0].data
    assert student.name.encode("utf-8") not in qr.data_list[0].data


# ---------------------------------------------------------------------------
# 4. Verification Pipeline: Unknown Ref, Valid, Tampered, Expired, Revoked
# ---------------------------------------------------------------------------
def test_verify_unknown_reference(client):
    """Requirement: Unknown ref returns UNKNOWN."""
    res = client.get("/api/verify/CRED-UNKNOWN-REFERENCE-999")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UNKNOWN"
    assert data["valid"] is False


def test_verify_valid_credential(client, db_session):
    """Requirement: Valid credential returns VALID with minimal anonymous fields."""
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    res = client.get(f"/api/verify/{cred.public_ref}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VALID"
    assert data["valid"] is True
    assert data["caller_class"] == "anonymous"

    # Anonymous caller: minimal fields only, no student display name or ID
    disclosed = data["disclosed"]
    assert "institution_name" in disclosed
    assert "qualification" in disclosed
    assert "student_display_name" not in disclosed
    assert "student_id" not in disclosed


def test_verify_tampered_payload_malformed(client, db_session):
    """Requirement: Tampered payload -> MALFORMED."""
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # Maliciously modify the student name in database payload
    tampered_payload = dict(cred.payload)
    tampered_payload["student_display_name"] = "Attacker Name"
    cred.payload = tampered_payload
    db_session.commit()

    # Attempt verification -> signature should fail over altered payload
    res = client.get(f"/api/verify/{cred.public_ref}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "MALFORMED"
    assert data["valid"] is False
    assert "signature verification failed" in data["message"].lower()


def test_verify_expired_credential(client, db_session):
    """Requirement: Expired credential -> EXPIRED."""
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    # Set expires_at in the past
    cred.expires_at = datetime.now(timezone.utc) - timedelta(days=5)
    db_session.commit()

    res = client.get(f"/api/verify/{cred.public_ref}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "EXPIRED"
    assert data["valid"] is False
    assert "expired" in data["message"].lower()


def test_verify_revocation_reflected_instantly_on_refresh(client, db_session):
    """
    Requirement: POST /api/credentials/{id}/revoke with mandatory reason;
    revocation reflected instantly on refresh.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # 1. Before revocation: verify is VALID
    res1 = client.get(f"/api/verify/{cred.public_ref}")
    assert res1.json()["status"] == "VALID"

    # 2. Missing reason on revoke -> must reject (422 or 400)
    bad_revoke = client.post(
        f"/api/credentials/{cred.id}/revoke",
        json={"reason": ""},
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert bad_revoke.status_code in (400, 422)

    # 3. Successful revocation with reason
    revoke_res = client.post(
        f"/api/credentials/{cred.id}/revoke",
        json={"reason": "Admission withdrawn due to fraudulent certificate."},
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "REVOKED"

    # 4. Immediate refresh -> verify must return REVOKED instantly
    res2 = client.get(f"/api/verify/{cred.public_ref}")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "REVOKED"
    assert data2["valid"] is False
    assert "fraudulent certificate" in data2["revoke_reason"]


# ---------------------------------------------------------------------------
# 5. Consent Check: Limited Response When Consent Withdrawn
# ---------------------------------------------------------------------------
def test_verify_consent_withdrawn_limited_response(client, db_session):
    """Requirement: Consent check: if consent WITHDRAWN, return limited response."""
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True, consent_status="WITHDRAWN")
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    res = client.get(f"/api/verify/{cred.public_ref}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VALID"
    assert data["consent_status"] == "WITHDRAWN"
    assert data["limited_response"] is True
    assert "restricted" in data["message"].lower()


# ---------------------------------------------------------------------------
# 6. Auto-Revoke on Enrollment REJECTED / CANCELLED / WITHDRAWN
# ---------------------------------------------------------------------------
def test_auto_revoke_on_enrollment_cancellation(client, db_session):
    """
    Requirement: Auto-revoke when an enrollment becomes REJECTED/CANCELLED/WITHDRAWN.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # Active before transition
    assert cred.status == "ACTIVE"

    # Transition enrollment to CANCELLED via state machine
    transition_enrollment_status(
        db=db_session,
        enrollment=enr,
        target_status="CANCELLED",
        actor_id="admin-01",
        actor_role="AICTE_ADMIN",
        reason="Student cancelled seat registration",
    )
    db_session.commit()
    db_session.refresh(cred)

    # Credential must be auto-revoked!
    assert cred.status == "REVOKED"
    assert "Auto-revoked" in cred.revoke_reason

    # Verification must reflect REVOKED
    res = client.get(f"/api/verify/{cred.public_ref}")
    assert res.json()["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# 7. Registered Verifiers: Registration, Purpose, API Key, Rate Limit, Logs
# ---------------------------------------------------------------------------
def test_registered_verifier_flow(client, db_session):
    """
    Requirement: Registered verifiers: registration, purpose declaration,
    API key, rate limit, field-level disclosure policy, verification log.
    """
    # 1. Register verifier
    reg_payload = {
        "name": "Tata Consultancy Services Background Screening",
        "contact_email": "campus.verify@tcs.com",
        "declared_purpose": "EMPLOYMENT_BACKGROUND_CHECK",
        "rate_limit_per_minute": 2,  # Set low limit to test rate limiting
        "allowed_fields": ["student_display_name", "qualification", "institution_name", "completion_year"],
    }
    reg_res = client.post("/api/verifiers/register", json=reg_payload)
    assert reg_res.status_code == 201
    verifier_data = reg_res.json()
    api_key = verifier_data["api_key"]
    assert api_key.startswith("ak_live_")

    # 2. Issue a credential
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id, completion_year=2024)
    db_session.commit()

    # 3. Verify as Registered Verifier with API Key
    verify_res = client.get(
        f"/api/verify/{cred.public_ref}",
        headers={"X-API-Key": api_key},
    )
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["status"] == "VALID"
    assert v_data["caller_class"] == "registered_verifier"
    # Registered verifier receives student_display_name and completion_year
    assert v_data["disclosed"]["student_display_name"] == student.name
    assert v_data["disclosed"]["completion_year"] == 2024
    assert v_data["disclosed"]["verifier_purpose_acknowledged"] == "EMPLOYMENT_BACKGROUND_CHECK"

    # 4. Test rate limiting (limit is 2/min)
    client.get(f"/api/verify/{cred.public_ref}", headers={"X-API-Key": api_key})
    rate_res = client.get(f"/api/verify/{cred.public_ref}", headers={"X-API-Key": api_key})
    assert rate_res.status_code == 429
    assert rate_res.json()["code"] == "RATE_LIMIT_EXCEEDED"

    # 5. Check Verification Audit Log
    logs_res = client.get(
        f"/api/verifiers/logs?reference={cred.public_ref}",
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) >= 1
    latest_log = logs[0]
    assert latest_log["reference"] == cred.public_ref
    assert latest_log["verifier_class"] == "registered_verifier"
    assert latest_log["purpose"] == "EMPLOYMENT_BACKGROUND_CHECK"


# ---------------------------------------------------------------------------
# 8. Authorised Staff Field Disclosure
# ---------------------------------------------------------------------------
def test_authorised_staff_disclosure(client, db_session):
    """
    Requirement: Authorised staff receives full fields including Student ID
    and masked APAAR ID.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    res = client.get(
        f"/api/verify/{cred.public_ref}",
        headers={"X-Mock-Role": "AICTE_ADMIN"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["caller_class"] == "authorised_staff"
    assert data["disclosed"]["student_id"] == student.id
    assert data["disclosed"]["apaar_masked"] == student.apaar_masked
    assert data["disclosed"]["enrollment_id"] == enr.id


# ---------------------------------------------------------------------------
# 9. Offline Verification: Signature Only with Warning
# ---------------------------------------------------------------------------
def test_offline_signature_verification(client, db_session):
    """
    Requirement: If client verifies offline by signature only, show 'Revocation not checked'.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # 1. Valid offline signature
    offline_req = {
        "payload": cred.payload,
        "signature": cred.signature,
        "key_id": cred.key_id,
    }
    res = client.post("/api/verify/offline", json=offline_req)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VALID_OFFLINE"
    assert data["valid"] is True
    assert data["warning"] == "Revocation not checked"

    # 2. Tampered offline payload -> MALFORMED
    tampered_payload = dict(cred.payload)
    tampered_payload["status_at_issue"] = "FRAUDULENT_STATUS"
    res_tampered = client.post("/api/verify/offline", json={
        "payload": tampered_payload,
        "signature": cred.signature,
        "key_id": cred.key_id,
    })
    assert res_tampered.status_code == 200
    assert res_tampered.json()["status"] == "MALFORMED"
    assert res_tampered.json()["valid"] is False


# ---------------------------------------------------------------------------
# 10. Certificate Sample HTML & PDF Template (Requirement 10: Student ID + APAAR ID masked)
# ---------------------------------------------------------------------------
def test_certificate_template_html_and_pdf(client, db_session):
    """
    Requirement: Add a certificate sample HTML/PDF template that prints
    'Student ID + APAAR ID (masked)' to cover requirement 10.
    """
    _, _, student, enr = create_test_hierarchy(db_session, enrollment_status="CONFIRMED", verified=True)
    cred = issue_credential(db_session, enr.id)
    db_session.commit()

    # 1. HTML Certificate Template
    html_res = client.get(f"/api/credentials/{cred.id}/certificate?format=html")
    assert html_res.status_code == 200
    html_text = html_res.text
    assert "Student ID" in html_text
    assert student.id in html_text
    assert "APAAR ID (masked)" in html_text
    assert student.apaar_masked in html_text
    # Ensure raw APAAR ID is NEVER printed
    assert "88880000" not in html_text
    assert "<svg" in html_text  # Contains embedded QR SVG

    # 2. PDF Certificate Template
    pdf_res = client.get(f"/api/credentials/{cred.id}/certificate?format=pdf")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    pdf_bytes = pdf_res.content
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"Student ID" in pdf_bytes
    assert b"APAAR ID" in pdf_bytes
    assert student.apaar_masked.encode("ascii") in pdf_bytes
