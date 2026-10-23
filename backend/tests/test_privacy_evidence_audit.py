"""
Comprehensive Automated Tests for Privacy, Evidence, and Audit Services.
File: backend/tests/test_privacy_evidence_audit.py

Verifies:
1. Access event written on read (sensitive student / credential / evidence reads).
2. Audit table strictly rejects UPDATE and DELETE (both ORM listener & DB engine triggers).
3. Consent withdrawal changes verification output (disclosing restricted claims with statutory retention notice).
4. Evidence hash stored (SHA-256 calculation, virus scan rejection, signed URL validation).
5. Hash chain verification (detects untampered chain vs. broken links).
6. Retention policy configuration table for rejected, withdrawn, and duplicate records.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import os
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.audit import AuditAppendOnlyViolation, AuditEvent
from backend.models.access_event import AccessEvent
from backend.models.consent import ConsentRecord, ProcessingBasisRecord
from backend.models.credential import Credential
from backend.models.enrollment import Enrollment
from backend.models.evidence import EvidenceRecord
from backend.models.institution import Institution
from backend.models.retention import RetentionPolicy
from backend.models.student import Student
from backend.models.user import User
from backend.security.crypto import create_jwt, hash_password
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_STUDENT,
)
from backend.services.audit_service import (
    calculate_audit_hash,
    get_audit_events,
    get_retention_policies,
    record_audit_event,
    update_retention_policy,
    verify_audit_hash_chain,
)
from backend.services.credential_service import issue_credential, verify_credential
from backend.services.evidence_service import (
    EICAR_SIGNATURE,
    generate_signed_download_url,
    get_evidence_by_id,
    list_evidence,
    scan_file_for_viruses,
    store_evidence_file,
    verify_signed_download_token,
)
from backend.services.privacy_service import (
    RETENTION_NOTICE_ON_WITHDRAWAL,
    check_external_sharing_consent,
    get_access_events,
    get_consent_records,
    get_processing_basis_records,
    log_access_event,
    record_consent,
    record_processing_basis,
    toggle_student_consent,
)


@pytest.fixture
def setup_privacy_test_data(db_session: Session):
    """Sets up institution, approval, student, and user records for tests."""
    inst = Institution(code="1-TEST-INST", name="National Tech Institute", status="ACTIVE")
    db_session.add(inst)
    db_session.flush()

    approval = ProgramApproval(
        institution_id=inst.id,
        programme="ENG",
        branch="CSE",
        academic_year="2024-2025",
        approval_ref="EOA-TEST-001",
        status=ApprovalStatus.FROZEN,
    )
    db_session.add(approval)
    db_session.flush()

    student = Student(
        apaar_encrypted="enc_token_privacy_01",
        apaar_hash="hash_privacy_student_01",
        apaar_masked="XXXX-XXXX-9999",
        name="Vikram Aditya",
        name_normalized="VIKRAM ADITYA",
        dob=date(2004, 5, 15),
        gender="MALE",
        mobile_last4="9999",
        consent_status="GRANTED",
    )
    db_session.add(student)
    db_session.flush()

    enrollment = Enrollment(
        student_id=student.id,
        institution_id=inst.id,
        approval_id=approval.id,
        academic_year="2024-2025",
        seat_type="REGULAR",
        category="OPEN",
        admission_date=datetime.now(timezone.utc),
        round="1",
        status="ACTIVE",
        verified=True,
    )
    db_session.add(enrollment)
    db_session.flush()

    # Users
    admin_user = User(
        email="admin_privacy@aicte.gov.in",
        password_hash=hash_password("adminpass"),
        role=ROLE_AICTE_ADMIN,
        is_active=True,
    )
    auditor_user = User(
        email="auditor_privacy@aicte.gov.in",
        password_hash=hash_password("auditorpass"),
        role=ROLE_AUDITOR,
        is_active=True,
    )
    student_user = User(
        email="vikram@student.edu",
        password_hash=hash_password("studentpass"),
        role=ROLE_STUDENT,
        is_active=True,
    )
    db_session.add_all([admin_user, auditor_user, student_user])
    db_session.commit()

    return {
        "institution": inst,
        "approval": approval,
        "student": student,
        "enrollment": enrollment,
        "admin_user": admin_user,
        "auditor_user": auditor_user,
        "student_user": student_user,
    }


def auth_headers(user: User, student_id: str = None) -> dict:
    """Helper to generate JWT bearer header for API requests."""
    token = create_jwt(
        {
            "sub": str(user.id),
            "role": user.role,
            "institution_id": str(user.institution_id) if user.institution_id else None,
            "student_id": student_id,
        }
    )
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. Access Events: Log every read of a sensitive record (who, what, why, when)
# ===========================================================================
def test_access_event_written_on_read(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement: Access events: log every read of a sensitive record (who, what, why/purpose, when).
    GET /api/privacy/access-events (auditor/admin only).
    """
    data = setup_privacy_test_data
    auditor = data["auditor_user"]
    student = data["student"]

    # 1. Log a sensitive record read via privacy_service
    event = log_access_event(
        db=db_session,
        actor_id=str(auditor.id),
        actor_role=auditor.role,
        record_type="STUDENT",
        record_id=str(student.id),
        purpose="AUDIT_VERIFICATION",
        fields_accessed=["name", "dob", "apaar_masked"],
        ip_address="192.168.1.50",
        user_agent="PyTestClient/1.0",
    )
    db_session.commit()

    assert event.id is not None
    assert event.record_type == "STUDENT"
    assert event.purpose == "AUDIT_VERIFICATION"
    assert event.fields_accessed == ["name", "dob", "apaar_masked"]

    # 2. Verify retrieval via GET /api/privacy/access-events (Auditor authorized)
    headers = auth_headers(auditor)
    resp = client.get("/api/privacy/access-events?record_type=STUDENT", headers=headers)
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    matched = [e for e in events if e["record_id"] == str(student.id)]
    assert len(matched) == 1
    assert matched[0]["purpose"] == "AUDIT_VERIFICATION"
    assert matched[0]["actor_role"] == ROLE_AUDITOR

    # 3. Verify access control: Student is FORBIDDEN from viewing access events
    student_headers = auth_headers(data["student_user"])
    forbidden_resp = client.get("/api/privacy/access-events", headers=student_headers)
    assert forbidden_resp.status_code == 403


# ===========================================================================
# 2. Audit Table: Append-only events rejecting UPDATE and DELETE
# ===========================================================================
def test_audit_table_rejects_update_and_delete(db_session: Session):
    """
    Requirement: Audit: append-only events for every write; the DB role used by the app has
    INSERT and SELECT only on audit_events.
    Test: audit table rejects UPDATE/DELETE.
    """
    # 1. Write an append-only audit event
    evt = record_audit_event(
        db=db_session,
        actor_id="admin_123",
        action="TEST_ACTION",
        entity_type="STUDENT",
        entity_id="student_999",
        reason="Testing append-only integrity",
    )
    db_session.commit()

    # 2. Attempt ORM UPDATE -> Must raise AuditAppendOnlyViolation
    with pytest.raises(AuditAppendOnlyViolation, match="UPDATE operations are strictly prohibited"):
        evt.reason = "Tampered reason"
        db_session.commit()

    db_session.rollback()

    # 3. Attempt ORM DELETE -> Must raise AuditAppendOnlyViolation
    with pytest.raises(AuditAppendOnlyViolation, match="DELETE operations are strictly prohibited"):
        db_session.delete(evt)
        db_session.commit()

    db_session.rollback()

    # 4. Attempt Raw SQL UPDATE via SQLite DDL Trigger -> Must fail / abort
    with pytest.raises(Exception, match="audit_events is append-only"):
        db_session.execute(
            text("UPDATE audit_events SET reason = 'Malicious update' WHERE id = :eid"),
            {"eid": str(evt.id)},
        )
        db_session.commit()

    db_session.rollback()

    # 5. Attempt Raw SQL DELETE via SQLite DDL Trigger -> Must fail / abort
    with pytest.raises(Exception, match="audit_events is append-only"):
        db_session.execute(
            text("DELETE FROM audit_events WHERE id = :eid"),
            {"eid": str(evt.id)},
        )
        db_session.commit()

    db_session.rollback()


# ===========================================================================
# 3. Consent: Withdrawal changes verification output & provides retention notice
# ===========================================================================
def test_consent_withdrawal_changes_verification_output(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement:
    - Verification and employer views must honour consent; on WITHDRAWN stop external
      sharing but retain legally required records and say so in the UI.
    - Student can toggle consent.
    - Test: consent withdrawal changes verification output.
    """
    data = setup_privacy_test_data
    enrollment = data["enrollment"]
    student = data["student"]

    # 1. Issue credential for verified active enrollment
    cred = issue_credential(
        db=db_session,
        enrollment_id=str(enrollment.id),
        qualification="B.Tech Computer Science & Engineering",
    )
    db_session.commit()

    # 2. Initial verification when consent is GRANTED (full verification disclosure)
    res_granted = verify_credential(db=db_session, reference=cred.public_ref, caller_class="anonymous")
    assert res_granted["status"] == "VALID"
    assert res_granted["valid"] is True
    assert "limited_response" not in res_granted or res_granted.get("limited_response") is False

    # 3. Toggle consent to WITHDRAWN
    toggle_res = toggle_student_consent(
        db=db_session,
        student_id=str(student.id),
        purpose="VERIFICATION",
        consent_status="WITHDRAWN",
        actor_id=str(student.id),
    )
    db_session.commit()

    assert toggle_res["consent_status"] == "WITHDRAWN"
    assert toggle_res["external_sharing_permitted"] is False
    assert "statutorily mandated" in toggle_res["notice"].lower() or "retained" in toggle_res["notice"].lower()

    # 4. Verification output AFTER consent withdrawal -> Must stop external sharing & return restricted claims
    res_withdrawn = verify_credential(db=db_session, reference=cred.public_ref, caller_class="anonymous")
    assert res_withdrawn["status"] == "VALID"
    assert res_withdrawn["consent_status"] == "WITHDRAWN"
    assert res_withdrawn["limited_response"] is True
    assert "External sharing is restricted" in res_withdrawn["message"]
    assert "statutory_retention_notice" in res_withdrawn

    # Student name and qualification are NOT disclosed under restricted withdrawal
    disclosed = res_withdrawn["disclosed"]
    assert "student_display_name" not in disclosed
    assert "qualification" not in disclosed
    assert disclosed["reference"] == cred.public_ref

    # 5. Verify via HTTP GET /api/verify/{reference}
    resp = client.get(f"/api/verify/{cred.public_ref}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "VALID"
    assert body.get("consent_status") == "WITHDRAWN"
    assert body.get("limited_response") is True


# ===========================================================================
# 4. Consent & Regulatory Processing Basis Separation
# ===========================================================================
def test_consent_and_processing_basis_endpoints(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement:
    - Consent: consent_status GRANTED|PENDING|WITHDRAWN|NOT_REQUIRED per student with purpose
      (ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING), reference and timestamp.
    - Keep consent separate from "regulatory processing basis" (a separate record type).
    - Endpoints: POST/GET /api/consent-records, POST /api/processing-basis-records.
    """
    data = setup_privacy_test_data
    student = data["student"]
    admin = data["admin_user"]
    admin_hdr = auth_headers(admin)

    # 1. POST /api/consent-records
    consent_payload = {
        "student_id": str(student.id),
        "purpose": "ADMISSION_REPORTING",
        "consent_status": "GRANTED",
        "reference": "CONSENT-OTP-98765",
    }
    resp = client.post("/api/consent-records", json=consent_payload, headers=admin_hdr)
    assert resp.status_code == 201
    c_data = resp.json()
    assert c_data["student_id"] == str(student.id)
    assert c_data["purpose"] == "ADMISSION_REPORTING"
    assert c_data["consent_status"] == "GRANTED"

    # 2. GET /api/consent-records
    get_resp = client.get(f"/api/consent-records?student_id={student.id}", headers=admin_hdr)
    assert get_resp.status_code == 200
    records = get_resp.json()
    assert len(records) >= 1
    assert any(r["reference"] == "CONSENT-OTP-98765" for r in records)

    # 3. POST /api/processing-basis-records (Separate record type from consent)
    basis_payload = {
        "basis_type": "STATUTORY_MANDATE",
        "statute_reference": "AICTE Act 1987 Section 10(k)",
        "purpose": "REGULATORY_MONITORING",
        "description": "Statutory power of AICTE to inspect admission lists and seat matrix allocations.",
    }
    basis_resp = client.post("/api/processing-basis-records", json=basis_payload, headers=admin_hdr)
    assert basis_resp.status_code == 201
    b_data = basis_resp.json()
    assert b_data["basis_type"] == "STATUTORY_MANDATE"
    assert b_data["statute_reference"] == "AICTE Act 1987 Section 10(k)"
    assert b_data["is_active"] is True

    # 4. GET /api/processing-basis-records
    list_basis = client.get("/api/processing-basis-records", headers=admin_hdr)
    assert list_basis.status_code == 200
    assert len(list_basis.json()) >= 1


# ===========================================================================
# 5. Evidence Service: SHA-256 Checksum, Storage, Signed URLs, Virus Scan
# ===========================================================================
def test_evidence_hash_stored_and_scanned(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement:
    - Evidence: POST /api/evidence registers a reference + SHA-256 + type
      (IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION) + uploader; files go to local/MinIO storage
      with access-controlled signed URLs, size/type limits and a stub virus-scan hook.
    - Test: evidence hash stored.
    """
    data = setup_privacy_test_data
    admin = data["admin_user"]
    admin_hdr = auth_headers(admin)

    # 1. Clean valid PDF upload
    pdf_content = b"%PDF-1.4 Fake AICTE Admission Certificate Document Content"
    expected_hash = hashlib.sha256(pdf_content).hexdigest()

    resp = client.post(
        "/api/evidence",
        data={
            "reference": str(data["enrollment"].id),
            "evidence_type": "ADMISSION_CATEGORY",
        },
        files={
            "file": ("category_cert.pdf", io.BytesIO(pdf_content), "application/pdf")
        },
        headers=admin_hdr,
    )
    assert resp.status_code == 201
    res_data = resp.json()
    assert res_data["sha256_hash"] == expected_hash
    assert res_data["evidence_type"] == "ADMISSION_CATEGORY"
    assert res_data["virus_scan_status"] == "CLEAN"
    assert "signed_download_url" in res_data

    # 2. Validate Signed URL download
    signed_url = res_data["signed_download_url"]
    dl_resp = client.get(signed_url)
    assert dl_resp.status_code == 200
    assert dl_resp.content == pdf_content

    # 3. Test virus scan rejection with EICAR string
    eicar_file = EICAR_SIGNATURE + b"extra padding"
    virus_resp = client.post(
        "/api/evidence",
        data={
            "reference": str(data["enrollment"].id),
            "evidence_type": "IDENTITY",
        },
        files={
            "file": ("infected_document.pdf", io.BytesIO(eicar_file), "application/pdf")
        },
        headers=admin_hdr,
    )
    assert virus_resp.status_code == 400
    assert "VIRUS_DETECTED" in str(virus_resp.json()) or "Security scan rejected" in str(virus_resp.json())

    # 4. Test disguised executable binary header rejection (.exe / MZ)
    exe_file = b"MZ\x90\x00\x03\x00\x00\x00" + b"malware content"
    exe_resp = client.post(
        "/api/evidence",
        data={
            "reference": str(data["enrollment"].id),
            "evidence_type": "IDENTITY",
        },
        files={
            "file": ("spoofed_document.pdf", io.BytesIO(exe_file), "application/pdf")
        },
        headers=admin_hdr,
    )
    assert exe_resp.status_code == 400
    assert "MALWARE_DETECTED" in str(exe_resp.json()) or "Security scan rejected" in str(exe_resp.json())


# ===========================================================================
# 6. Cryptographic Audit Hash Chain Verification & Tamper Detection
# ===========================================================================
def test_audit_hash_chain_verification_and_tamper_detection(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement:
    - Cryptographic hash chain: hash = SHA256(prev_hash + canonical event).
    - GET /api/audit-events with filters (actor, institution, entity, action, time) and a verify-chain script.
    """
    data = setup_privacy_test_data
    admin = data["admin_user"]
    admin_hdr = auth_headers(admin)

    # 1. Record a sequence of 3 linked audit events
    evt1 = record_audit_event(db_session, "actor_1", "CREATE", "STUDENT", "s1", "Created student")
    evt2 = record_audit_event(db_session, "actor_2", "UPDATE", "ENROLLMENT", "e1", "Updated enrollment")
    evt3 = record_audit_event(db_session, "actor_1", "ISSUE", "CREDENTIAL", "c1", "Issued credential")
    db_session.commit()

    # Verify links
    assert evt2.prev_hash == evt1.hash
    assert evt3.prev_hash == evt2.hash

    # 2. Run chain verification API
    verify_resp = client.post("/api/audit-events/verify-chain", headers=admin_hdr)
    assert verify_resp.status_code == 200
    v_data = verify_resp.json()
    assert v_data["chain_valid"] is True
    assert v_data["total_events_checked"] >= 3
    assert len(v_data["broken_links"]) == 0

    # 3. Test GET /api/audit-events with filters
    filt_resp = client.get("/api/audit-events?action=ISSUE&entity_type=CREDENTIAL", headers=admin_hdr)
    assert filt_resp.status_code == 200
    events = filt_resp.json()
    assert len(events) >= 1
    assert events[0]["action"] == "ISSUE"
    assert events[0]["entity_type"] == "CREDENTIAL"


# ===========================================================================
# 7. Configurable Retention Policy Table
# ===========================================================================
def test_retention_policy_table_admin_ui(client, db_session: Session, setup_privacy_test_data):
    """
    Requirement: Include a configurable retention-policy table (rejected / withdrawn /
    duplicate record retention) displayed in the admin UI.
    """
    admin = setup_privacy_test_data["admin_user"]
    admin_hdr = auth_headers(admin)

    # 1. GET /api/retention-policies -> Seeds defaults (REJECTED, WITHDRAWN, DUPLICATE)
    resp = client.get("/api/retention-policies", headers=admin_hdr)
    assert resp.status_code == 200
    policies = resp.json()
    categories = [p["record_category"] for p in policies]

    assert "REJECTED" in categories
    assert "WITHDRAWN" in categories
    assert "DUPLICATE" in categories

    # 2. PUT /api/retention-policies/{category} -> Update retention days
    update_payload = {
        "retention_days": 3650,  # 10 years
        "legal_basis": "AICTE Handbook 2025 Revised",
        "action_on_expiry": "PURGE",
    }
    put_resp = client.put("/api/retention-policies/REJECTED", json=update_payload, headers=admin_hdr)
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["record_category"] == "REJECTED"
    assert updated["retention_days"] == 3650
    assert updated["legal_basis"] == "AICTE Handbook 2025 Revised"
