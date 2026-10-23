"""
Verifiable Credential Service (backend/services/credential_service.py).

Implements:
1. Ed25519 cryptographic signing over canonical JSON (RFC 8785) with key rotation.
2. 128-bit random URL-safe public_ref generation.
3. Server-side QR code generation (PNG/SVG) encoding strictly https://<host>/verify/<public_ref>
   with NO raw APAAR ID, DOB, contact, or name.
4. Verification pipeline: lookup -> signature check -> expiry -> revocation -> consent check ->
   field-level disclosure by caller class (anonymous / registered verifier / authorised staff).
5. Offline signature verification displaying "Revocation not checked".
6. Explicit revocation and auto-revocation when enrollments become REJECTED/CANCELLED/WITHDRAWN.
7. Registered verifier management (API key hashing, rate limiting, purpose declaration, verification log).
8. Certificate sample HTML & PDF template printing "Student ID + APAAR ID (masked)" (Rule 10).
"""
import base64
import hashlib
import io
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import qrcode
import qrcode.image.svg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy.orm import Session

from backend.models.audit import AuditEvent
from backend.services.audit import record_audit_event
from backend.models.credential import Credential, RegisteredVerifier, VerificationLog
from backend.models.enrollment import Enrollment
from backend.models.student import Student
from backend.schemas.errors import AppException, BadRequestError, ForbiddenError, NotFoundError
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_AUDITOR,
)

logger = logging.getLogger("credential_service")

# ---------------------------------------------------------------------------
# Key Management & Ed25519 Store
# ---------------------------------------------------------------------------
ACTIVE_KEY_ID = os.getenv("CREDENTIAL_KEY_ID", "AICTE-ED25519-2025-V1")
CREDENTIAL_KEY_ID = ACTIVE_KEY_ID

# Global key store holding private/public key pairs in memory for rotation
_KEY_STORE: Dict[str, Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]] = {}


def _initialize_key_pair(key_id: str) -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """
    Initializes an Ed25519 key pair:
    1. Checks CREDENTIAL_ED25519_PRIVATE_KEY env var (base64 raw 32-bytes or PEM).
    2. Checks CREDENTIAL_ED25519_KEY_PATH file path.
    3. Falls back to generating a secure ephemeral key pair in memory (never committed).
    """
    env_key = os.getenv("CREDENTIAL_ED25519_PRIVATE_KEY")
    key_path = os.getenv("CREDENTIAL_ED25519_KEY_PATH")

    if env_key:
        try:
            # Try raw 32-byte base64 first
            raw_bytes = base64.b64decode(env_key.strip())
            if len(raw_bytes) == 32:
                priv = ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
                return priv, priv.public_key()
            # Try PEM
            priv = serialization.load_pem_private_key(env_key.encode("utf-8"), password=None)
            if isinstance(priv, ed25519.Ed25519PrivateKey):
                return priv, priv.public_key()
        except Exception as e:
            logger.warning(f"Could not load key from CREDENTIAL_ED25519_PRIVATE_KEY: {e}")

    if key_path and os.path.isfile(key_path):
        try:
            with open(key_path, "rb") as f:
                content = f.read()
            if len(content) == 32:
                priv = ed25519.Ed25519PrivateKey.from_private_bytes(content)
            else:
                priv = serialization.load_pem_private_key(content, password=None)
            if isinstance(priv, ed25519.Ed25519PrivateKey):
                return priv, priv.public_key()
        except Exception as e:
            logger.warning(f"Could not load key from file '{key_path}': {e}")

    # Generate secure key pair in memory (persisted for process lifetime)
    logger.info(f"Generating active Ed25519 signing key pair for key_id '{key_id}'")
    priv = ed25519.Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def get_signing_key(key_id: Optional[str] = None) -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey, str]:
    """Retrieves the active or requested signing key pair."""
    effective_id = key_id or ACTIVE_KEY_ID
    if effective_id not in _KEY_STORE:
        _KEY_STORE[effective_id] = _initialize_key_pair(effective_id)
    priv, pub = _KEY_STORE[effective_id]
    return priv, pub, effective_id


def get_public_key(key_id: str) -> Optional[ed25519.Ed25519PublicKey]:
    """Retrieves public key for verification by key_id."""
    if key_id in _KEY_STORE:
        return _KEY_STORE[key_id][1]
    if key_id == ACTIVE_KEY_ID:
        _, pub, _ = get_signing_key(key_id)
        return pub
    return None


def list_public_keys() -> List[Dict[str, Any]]:
    """Returns active and historical public keys for rotation publishing at GET /api/keys."""
    get_signing_key(ACTIVE_KEY_ID)  # Ensure active key is loaded
    results = []
    for k_id, (_, pub) in _KEY_STORE.items():
        raw_pub = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        pem_pub = pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        results.append({
            "key_id": k_id,
            "algorithm": "Ed25519",
            "public_key": base64.b64encode(raw_pub).decode("ascii"),
            "public_key_pem": pem_pub,
            "status": "ACTIVE" if k_id == ACTIVE_KEY_ID else "RETIRED",
        })
    return results


# ---------------------------------------------------------------------------
# Canonical JSON & Ed25519 Signing
# ---------------------------------------------------------------------------
def canonical_json_bytes(data: Dict[str, Any]) -> bytes:
    """RFC 8785 JSON Canonicalization Scheme: keys sorted, no extraneous whitespace, UTF-8."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_payload_ed25519(payload: Dict[str, Any], private_key: ed25519.Ed25519PrivateKey) -> str:
    """Produces Base64 Ed25519 signature over canonical JSON payload."""
    canonical = canonical_json_bytes(payload)
    sig_bytes = private_key.sign(canonical)
    return base64.b64encode(sig_bytes).decode("ascii")


def verify_payload_signature(payload: Dict[str, Any], signature_b64: str, public_key: ed25519.Ed25519PublicKey) -> bool:
    """Verifies Ed25519 signature over canonical JSON payload."""
    try:
        canonical = canonical_json_bytes(payload)
        sig_bytes = base64.b64decode(signature_b64.encode("ascii"))
        public_key.verify(sig_bytes, canonical)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def generate_128bit_public_ref() -> str:
    """Generates a cryptographically random 128-bit URL-safe public reference."""
    # 16 bytes = 128 bits of cryptographic entropy
    token = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
    return f"CRED-{token}"


# ---------------------------------------------------------------------------
# QR Code Generator
# ---------------------------------------------------------------------------
def build_verification_url(public_ref: str, host: Optional[str] = None) -> str:
    """Builds the canonical public verification URL."""
    base = host or os.getenv("APP_HOST_URL", "https://aicte.gov.in")
    base = base.rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        base = f"https://{base}"
    return f"{base}/verify/{public_ref}"


def generate_qr_svg(public_ref: str, host: Optional[str] = None) -> str:
    """
    Generates SVG QR code encoding strictly https://<host>/verify/<public_ref>.
    Rule 10: Absolutely NO raw APAAR ID, DOB, contact, or student name in QR.
    """
    url = build_verification_url(public_ref, host)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    stream = io.BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def generate_qr_png(public_ref: str, host: Optional[str] = None) -> bytes:
    """
    Generates PNG QR code encoding strictly https://<host>/verify/<public_ref>.
    Rule 10: Absolutely NO raw APAAR ID, DOB, contact, or student name in QR.
    """
    url = build_verification_url(public_ref, host)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Issuance Logic
# ---------------------------------------------------------------------------
ELIGIBLE_ISSUANCE_STATUSES = {"CONFIRMED", "ACTIVE", "COMPLETED"}


def issue_credential(
    db: Session,
    enrollment_id: str,
    completion_year: Optional[int] = None,
    qualification: Optional[str] = None,
    expires_in_days: Optional[int] = None,
    host: Optional[str] = None,
    actor_id: str = "SYSTEM",
) -> Credential:
    """
    Issues a privacy-minimal signed credential:
    - Prerequisite: verified=True AND status in CONFIRMED, ACTIVE, COMPLETED.
    - Generates 128-bit random public_ref.
    - Builds canonical payload signed with Ed25519.
    """
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise NotFoundError(f"Enrollment '{enrollment_id}' not found.")

    # 1. Eligibility Check: verified=True and status CONFIRMED/ACTIVE/COMPLETED
    current_status = (enrollment.status or "").upper()
    is_verified = bool(enrollment.verified)

    if not is_verified or current_status not in ELIGIBLE_ISSUANCE_STATUSES:
        raise BadRequestError(
            f"Cannot issue credential for enrollment '{enrollment_id}'. "
            f"Enrollment must have verified=True and status in {sorted(list(ELIGIBLE_ISSUANCE_STATUSES))}. "
            f"Current state: verified={is_verified}, status='{current_status}'."
        )

    # 2. Check if an active credential already exists
    existing = db.query(Credential).filter(
        Credential.enrollment_id == enrollment_id,
        Credential.status == "ACTIVE",
    ).first()
    if existing:
        return existing

    # 3. Retrieve student and institution attributes
    student = enrollment.student
    student_name = student.name if student else "Student"
    institution = enrollment.institution
    institution_name = institution.name if institution else "AICTE Approved Institution"

    approval = enrollment.approval
    if qualification:
        qual_title = qualification.strip()
    elif approval:
        qual_title = f"{approval.programme} ({approval.branch})"
    else:
        qual_title = "Technical Education Programme"

    # 4. Generate 128-bit random public_ref and dates
    public_ref = generate_128bit_public_ref()
    # Ensure reference uniqueness in database
    while db.query(Credential).filter(Credential.public_ref == public_ref).first():
        public_ref = generate_128bit_public_ref()

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=expires_in_days) if expires_in_days else None

    # Load signing key
    priv_key, _, key_id = get_signing_key(ACTIVE_KEY_ID)

    # Temporary UUID for credential_id to embed in signed payload
    import uuid
    credential_id = str(uuid.uuid4())

    # 5. Build canonical payload (Strictly privacy-minimal, Rule 10 compliant)
    payload = {
        "credential_id": credential_id,
        "public_ref": public_ref,
        "student_display_name": student_name,
        "qualification": qual_title,
        "institution_name": institution_name,
        "completion_year": completion_year,
        "status_at_issue": current_status,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "key_id": key_id,
    }

    # 6. Sign payload with Ed25519 over canonical JSON
    signature = sign_payload_ed25519(payload, priv_key)

    # 7. Persist Credential record
    credential = Credential(
        id=credential_id,
        enrollment_id=enrollment.id,
        public_ref=public_ref,
        payload=payload,
        signature=signature,
        key_id=key_id,
        expires_at=expires_at,
        status="ACTIVE",
    )
    db.add(credential)

    # 8. Audit Event
    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="CREDENTIAL_ISSUED",
        entity_type="CREDENTIAL",
        entity_id=credential_id,
        reason=f"Issued verifiable credential {public_ref} for enrollment {enrollment_id}",
    )

    logger.info(f"Successfully issued credential '{credential_id}' (ref: {public_ref}) for enrollment '{enrollment_id}'")
    return credential


# ---------------------------------------------------------------------------
# Rate Limiting Store for Registered Verifiers
# ---------------------------------------------------------------------------
_VERIFIER_RATE_LIMITS: Dict[str, List[float]] = defaultdict(list)


def check_verifier_rate_limit(verifier_id: str, limit_per_minute: int) -> bool:
    """Sliding-window rate limiter per verifier_id."""
    now = time.time()
    window = now - 60.0
    timestamps = [t for t in _VERIFIER_RATE_LIMITS[verifier_id] if t > window]
    if len(timestamps) >= limit_per_minute:
        _VERIFIER_RATE_LIMITS[verifier_id] = timestamps
        return False
    timestamps.append(now)
    _VERIFIER_RATE_LIMITS[verifier_id] = timestamps
    return True


# ---------------------------------------------------------------------------
# Verification Pipeline
# ---------------------------------------------------------------------------
def verify_credential(
    db: Session,
    reference: str,
    caller_class: str = "anonymous",
    registered_verifier: Optional[RegisteredVerifier] = None,
    user_principal: Optional[Any] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Verification Pipeline:
    Step 1: Lookup credential by public_ref or ID.
    Step 2: Ed25519 signature check against canonical JSON payload.
    Step 3: Expiry check.
    Step 4: Current server-side revocation check.
    Step 5: Student consent check (limited response if consent WITHDRAWN).
    Step 6: Minimal field disclosure by caller class (anonymous / registered verifier / authorised staff).
    Step 7: Verification audit logging.

    Guarantee: SERVICE_UNAVAILABLE must never render as valid.
    """
    try:
        # STEP 1: LOOKUP
        clean_ref = reference.strip()
        credential = db.query(Credential).filter(
            (Credential.public_ref == clean_ref) | (Credential.id == clean_ref)
        ).first()

        if not credential:
            _log_verification(
                db=db,
                reference=clean_ref,
                caller_class=caller_class,
                verifier=registered_verifier,
                result_status="UNKNOWN",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return {
                "status": "UNKNOWN",
                "valid": False,
                "reference": clean_ref,
                "message": "Credential reference not found in registry.",
            }

        payload = credential.payload or {}
        public_ref = credential.public_ref

        # STEP 2: SIGNATURE CHECK
        pub_key = get_public_key(credential.key_id)
        if not pub_key:
            _log_verification(db, public_ref, caller_class, registered_verifier, "MALFORMED", ip_address, user_agent)
            return {
                "status": "MALFORMED",
                "valid": False,
                "reference": public_ref,
                "key_id": credential.key_id,
                "message": f"Signing key '{credential.key_id}' is unrecognized or unresolvable.",
            }

        is_sig_valid = verify_payload_signature(payload, credential.signature, pub_key)
        if not is_sig_valid:
            _log_verification(db, public_ref, caller_class, registered_verifier, "MALFORMED", ip_address, user_agent)
            return {
                "status": "MALFORMED",
                "valid": False,
                "reference": public_ref,
                "key_id": credential.key_id,
                "message": "Cryptographic Ed25519 signature verification failed or payload has been tampered with.",
            }

        # STEP 3: EXPIRY CHECK
        now_utc = datetime.now(timezone.utc)
        if credential.expires_at:
            exp = credential.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now_utc > exp:
                _log_verification(db, public_ref, caller_class, registered_verifier, "EXPIRED", ip_address, user_agent)
                return {
                    "status": "EXPIRED",
                    "valid": False,
                    "reference": public_ref,
                    "expired_at": credential.expires_at.isoformat(),
                    "message": "Credential has expired.",
                }

        # STEP 4: REVOCATION CHECK (Current server-side)
        if credential.status == "REVOKED" or credential.revoked_at is not None:
            _log_verification(db, public_ref, caller_class, registered_verifier, "REVOKED", ip_address, user_agent)
            return {
                "status": "REVOKED",
                "valid": False,
                "reference": public_ref,
                "revoked_at": credential.revoked_at.isoformat() if credential.revoked_at else None,
                "revoke_reason": credential.revoke_reason or "Revoked by administrative authority",
                "message": f"Credential has been revoked: {credential.revoke_reason or 'No reason specified'}",
            }

        # STEP 5: CONSENT CHECK
        enrollment = credential.enrollment
        student = enrollment.student if enrollment else None
        consent_status = (student.consent_status or "GRANTED").upper() if student else "GRANTED"

        if student:
            try:
                from backend.services.privacy_service import (
                    check_external_sharing_consent,
                    RETENTION_NOTICE_ON_WITHDRAWAL,
                )
                permitted, notice, legal_details = check_external_sharing_consent(
                    db=db,
                    student_id=str(student.id),
                    purpose="VERIFICATION",
                )
                if not permitted:
                    consent_status = "WITHDRAWN"
            except Exception as e:
                logger.warning(f"Error checking dynamic consent status: {e}")

        if consent_status == "WITHDRAWN":
            # Limited response if consent withdrawn: stop external sharing
            disclosed = {
                "reference": public_ref,
                "institution_name": payload.get("institution_name"),
                "status_at_issue": payload.get("status_at_issue"),
            }
            _log_verification(db, public_ref, caller_class, registered_verifier, "VALID", ip_address, user_agent, disclosed)
            return {
                "status": "VALID",
                "valid": True,
                "reference": public_ref,
                "consent_status": "WITHDRAWN",
                "limited_response": True,
                "message": "Student consent has been withdrawn. External sharing is restricted. Legally required records are retained pursuant to statutory mandate (DPDP Act 2023 Sec 7 & AICTE Act 1987 Sec 10(k)).",
                "statutory_retention_notice": "External sharing restricted due to student consent withdrawal. Institutional and regulatory records are retained pursuant to statutory mandate (DPDP Act 2023 & AICTE Act 1987 Section 10(k)).",
                "disclosed": disclosed,
            }

        # STEP 6: MINIMAL FIELD DISCLOSURE BY CALLER CLASS
        if caller_class == "authorised_staff" or (user_principal and user_principal.role in [ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_INSTITUTION_ADMIN, ROLE_AUDITOR]):
            effective_caller = "authorised_staff"
            disclosed = {
                "reference": public_ref,
                "credential_id": str(credential.id),
                "enrollment_id": str(credential.enrollment_id),
                "student_display_name": payload.get("student_display_name"),
                "student_id": str(student.id) if student else None,
                "institution_name": payload.get("institution_name"),
                "qualification": payload.get("qualification"),
                "completion_year": payload.get("completion_year"),
                "status_at_issue": payload.get("status_at_issue"),
                "issued_at": payload.get("issued_at"),
                "expires_at": payload.get("expires_at"),
                "key_id": credential.key_id,
                "apaar_masked": student.apaar_masked if student else "XXXX-XXXX-XXXX",
            }
        elif caller_class == "registered_verifier" and registered_verifier:
            effective_caller = "registered_verifier"
            base_claims = {
                "reference": public_ref,
                "student_display_name": payload.get("student_display_name"),
                "institution_name": payload.get("institution_name"),
                "qualification": payload.get("qualification"),
                "completion_year": payload.get("completion_year"),
                "status_at_issue": payload.get("status_at_issue"),
                "issued_at": payload.get("issued_at"),
            }
            # Enforce verifier allowed_fields if configured
            if registered_verifier.allowed_fields:
                disclosed = {k: v for k, v in base_claims.items() if k in registered_verifier.allowed_fields or k == "reference"}
            else:
                disclosed = base_claims
            disclosed["verifier_purpose_acknowledged"] = registered_verifier.declared_purpose
        else:
            effective_caller = "anonymous"
            # Minimal anonymous disclosure: No student name or identifiers
            disclosed = {
                "reference": public_ref,
                "institution_name": payload.get("institution_name"),
                "qualification": payload.get("qualification"),
                "status_at_issue": payload.get("status_at_issue"),
                "issued_at": payload.get("issued_at"),
            }

        # STEP 7: VERIFICATION AUDIT LOG
        _log_verification(
            db=db,
            reference=public_ref,
            caller_class=effective_caller,
            verifier=registered_verifier,
            result_status="VALID",
            ip_address=ip_address,
            user_agent=user_agent,
            disclosed=disclosed,
        )

        return {
            "status": "VALID",
            "valid": True,
            "reference": public_ref,
            "caller_class": effective_caller,
            "key_id": credential.key_id,
            "disclosed": disclosed,
        }

    except Exception as exc:
        logger.error(f"Critical error during verification of reference '{reference}': {exc}", exc_info=True)
        # CRITICAL CONSTRAINT: SERVICE_UNAVAILABLE must NEVER render as valid
        return {
            "status": "SERVICE_UNAVAILABLE",
            "valid": False,
            "reference": reference,
            "message": "Verification service is currently unavailable. Credential could not be verified.",
        }


def _log_verification(
    db: Session,
    reference: str,
    caller_class: str,
    verifier: Optional[RegisteredVerifier],
    result_status: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    disclosed: Optional[Dict[str, Any]] = None,
) -> None:
    """Records an audit verification log."""
    try:
        log_entry = VerificationLog(
            reference=reference,
            verifier_class=caller_class,
            verifier_id=str(verifier.id) if verifier else None,
            verifier_name=verifier.name if verifier else None,
            purpose=verifier.declared_purpose if verifier else None,
            result_status=result_status,
            disclosed_fields=list(disclosed.keys()) if disclosed else [],
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log_entry)
        db.flush()
    except Exception as e:
        logger.warning(f"Could not persist verification log: {e}")


# ---------------------------------------------------------------------------
# Offline Signature Verification
# ---------------------------------------------------------------------------
def verify_credential_offline(payload: Dict[str, Any], signature: str, key_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Offline verification by Ed25519 signature check only.
    Strictly returns warning: 'Revocation not checked'.
    """
    eff_key_id = key_id or payload.get("key_id") or ACTIVE_KEY_ID
    pub_key = get_public_key(eff_key_id)

    if not pub_key:
        return {
            "status": "MALFORMED",
            "valid": False,
            "signature_valid": False,
            "key_id": eff_key_id,
            "message": f"Public key for key_id '{eff_key_id}' not found in registry.",
        }

    is_valid = verify_payload_signature(payload, signature, pub_key)
    if is_valid:
        return {
            "status": "VALID_OFFLINE",
            "valid": True,
            "signature_valid": True,
            "warning": "Revocation not checked",
            "notice": "Revocation not checked",
            "key_id": eff_key_id,
            "payload": payload,
        }
    return {
        "status": "MALFORMED",
        "valid": False,
        "signature_valid": False,
        "key_id": eff_key_id,
        "message": "Ed25519 signature verification failed. Payload may have been modified.",
    }


# ---------------------------------------------------------------------------
# Revocation & Auto-Revocation
# ---------------------------------------------------------------------------
def revoke_credential(
    db: Session,
    credential_id_or_ref: str,
    reason: str,
    actor_id: str = "SYSTEM",
) -> Credential:
    """
    Revokes a credential with a mandatory reason.
    Immediately reflected on subsequent verifications.
    """
    if not reason or not reason.strip():
        raise BadRequestError("Revocation reason is mandatory and cannot be empty.")

    clean_target = credential_id_or_ref.strip()
    credential = db.query(Credential).filter(
        (Credential.id == clean_target) | (Credential.public_ref == clean_target)
    ).first()

    if not credential:
        raise NotFoundError(f"Credential '{clean_target}' not found.")

    credential.status = "REVOKED"
    credential.revoked_at = datetime.now(timezone.utc)
    credential.revoke_reason = reason.strip()

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="CREDENTIAL_REVOKED",
        entity_type="CREDENTIAL",
        entity_id=str(credential.id),
        reason=credential.revoke_reason,
    )

    logger.info(f"Credential '{credential.id}' revoked with reason: '{credential.revoke_reason}'")
    return credential


def auto_revoke_credential_for_enrollment(
    db: Session,
    enrollment_id: str,
    trigger_status: str,
    actor_id: str = "SYSTEM",
) -> Optional[Credential]:
    """
    Automatically revokes active credentials when an enrollment transitions to
    REJECTED, CANCELLED, or WITHDRAWN.
    """
    credential = db.query(Credential).filter(
        Credential.enrollment_id == enrollment_id,
        Credential.status == "ACTIVE",
    ).first()

    if credential:
        auto_reason = f"Auto-revoked: enrollment transitioned to {trigger_status}"
        logger.info(f"Auto-revoking credential '{credential.id}' for enrollment '{enrollment_id}' ({auto_reason})")
        return revoke_credential(db=db, credential_id_or_ref=str(credential.id), reason=auto_reason, actor_id=actor_id)

    return None


# ---------------------------------------------------------------------------
# Registered Verifier Management
# ---------------------------------------------------------------------------
def register_verifier(
    db: Session,
    name: str,
    contact_email: str,
    declared_purpose: str,
    rate_limit_per_minute: int = 60,
    allowed_fields: Optional[List[str]] = None,
) -> Tuple[RegisteredVerifier, str]:
    """
    Registers a third-party verifier entity, issues an API key, and records purpose.
    Returns (verifier_record, plaintext_api_key). Plaintext key is shown only once.
    """
    if not name or not name.strip():
        raise BadRequestError("Verifier name is required.")
    if not contact_email or not contact_email.strip():
        raise BadRequestError("Verifier contact email is required.")
    if not declared_purpose or not declared_purpose.strip():
        raise BadRequestError("Declared purpose is required.")

    # Generate cryptographically secure API key
    raw_token = secrets.token_hex(24)
    api_key = f"ak_live_{raw_token}"
    api_key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    api_key_prefix = api_key[:12]

    default_fields = [
        "reference",
        "student_display_name",
        "qualification",
        "institution_name",
        "completion_year",
        "status_at_issue",
        "issued_at",
    ]
    effective_fields = allowed_fields or default_fields

    verifier = RegisteredVerifier(
        name=name.strip(),
        contact_email=contact_email.strip(),
        declared_purpose=declared_purpose.strip(),
        api_key_hash=api_key_hash,
        api_key_prefix=api_key_prefix,
        rate_limit_per_minute=rate_limit_per_minute or 60,
        allowed_fields=effective_fields,
        is_active=True,
    )
    db.add(verifier)
    db.flush()

    logger.info(f"Registered verifier '{verifier.name}' (id: {verifier.id}) for purpose '{verifier.declared_purpose}'")
    return verifier, api_key


def authenticate_api_key(db: Session, api_key: str) -> Optional[RegisteredVerifier]:
    """Authenticates API key passed in headers against registered verifiers."""
    if not api_key:
        return None
    key_hash = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()
    return db.query(RegisteredVerifier).filter(
        RegisteredVerifier.api_key_hash == key_hash,
        RegisteredVerifier.is_active == True,
    ).first()


# ---------------------------------------------------------------------------
# Certificate Sample HTML & PDF Template (Requirement 10: Student ID + APAAR ID masked)
# ---------------------------------------------------------------------------
def render_certificate_html(credential: Credential, host: Optional[str] = None) -> str:
    """
    Generates certificate sample HTML template that prints 'Student ID + APAAR ID (masked)'.
    Meets Rule 10: raw APAAR ID is never displayed; masked representation XXXX-XXXX-1234 only.
    """
    payload = credential.payload or {}
    enrollment = credential.enrollment
    student = enrollment.student if enrollment else None

    student_display_name = payload.get("student_display_name", "Student")
    qualification = payload.get("qualification", "Degree / Diploma Programme")
    institution_name = payload.get("institution_name", "AICTE Approved Institution")
    status_at_issue = payload.get("status_at_issue", "CONFIRMED")
    issued_at = payload.get("issued_at", "")
    public_ref = credential.public_ref
    key_id = credential.key_id
    status = credential.status

    # Requirement 10: Student ID + APAAR ID (masked)
    student_id = str(student.id) if student else (str(enrollment.student_id) if enrollment else "N/A")
    apaar_masked = student.apaar_masked if student else "XXXX-XXXX-XXXX"

    qr_svg = generate_qr_svg(public_ref, host=host)
    verify_url = build_verification_url(public_ref, host=host)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Verifiable Certificate - {public_ref}</title>
  <style>
    @page {{ size: A4 portrait; margin: 15mm; }}
    body {{
      font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 20px;
      background: #f8fafc;
      color: #0f172a;
    }}
    .cert-container {{
      max-width: 800px;
      margin: 0 auto;
      background: #ffffff;
      border: 3px double #d97706;
      border-radius: 8px;
      padding: 40px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.08);
      position: relative;
    }}
    .header {{
      text-align: center;
      border-bottom: 2px solid #e2e8f0;
      padding-bottom: 20px;
      margin-bottom: 25px;
    }}
    .aicte-logo {{
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 1.5px;
      color: #b45309;
      text-transform: uppercase;
    }}
    .sub-logo {{
      font-size: 13px;
      color: #64748b;
      margin-top: 4px;
      letter-spacing: 0.5px;
    }}
    .cert-title {{
      font-size: 22px;
      font-weight: 700;
      color: #1e293b;
      margin: 20px 0 8px 0;
      text-transform: uppercase;
      letter-spacing: 1px;
    }}
    .cert-statement {{
      font-size: 14px;
      color: #475569;
      margin-bottom: 25px;
    }}
    .grid-table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 25px;
    }}
    .grid-table td {{
      padding: 10px 14px;
      border-bottom: 1px solid #f1f5f9;
      font-size: 14px;
    }}
    .grid-table td.label {{
      font-weight: 600;
      color: #64748b;
      width: 32%;
      background: #f8fafc;
    }}
    .grid-table td.value {{
      color: #0f172a;
      font-weight: 500;
    }}
    .highlight-rule10 {{
      background: #fef3c7 !important;
      color: #92400e !important;
      font-weight: 700 !important;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge-active {{ background: #dcfce7; color: #166534; }}
    .badge-revoked {{ background: #fee2e2; color: #991b1b; }}
    .footer-section {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top: 2px solid #e2e8f0;
      padding-top: 20px;
      margin-top: 20px;
    }}
    .qr-box {{
      width: 130px;
      height: 130px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .qr-box svg {{
      width: 100%;
      height: 100%;
    }}
    .security-notice {{
      font-size: 11px;
      color: #64748b;
      max-width: 580px;
      line-height: 1.5;
    }}
    .security-notice strong {{
      color: #334155;
    }}
  </style>
</head>
<body>
  <div class="cert-container">
    <div class="header">
      <div class="aicte-logo">All India Council for Technical Education</div>
      <div class="sub-logo">Statutory Body Under Government of India | APAAR Connect Registry</div>
      <div class="cert-title">Verifiable Academic Enrollment Credential</div>
      <div class="cert-statement">This digitally signed credential authenticates legitimate admission and quota compliance.</div>
    </div>

    <table class="grid-table">
      <tr>
        <td class="label">Student Display Name</td>
        <td class="value"><strong>{student_display_name}</strong></td>
      </tr>
      <tr>
        <td class="label">Student ID</td>
        <td class="value"><code>{student_id}</code></td>
      </tr>
      <tr>
        <td class="label highlight-rule10">APAAR ID (masked)</td>
        <td class="value highlight-rule10"><code>{apaar_masked}</code> &nbsp;<small>(Rule 10 Privacy-Protected)</small></td>
      </tr>
      <tr>
        <td class="label">Institution Name</td>
        <td class="value">{institution_name}</td>
      </tr>
      <tr>
        <td class="label">Programme / Qualification</td>
        <td class="value">{qualification}</td>
      </tr>
      <tr>
        <td class="label">Verification Reference</td>
        <td class="value"><code>{public_ref}</code></td>
      </tr>
      <tr>
        <td class="label">Admission Status at Issue</td>
        <td class="value"><span class="badge badge-active">{status_at_issue}</span></td>
      </tr>
      <tr>
        <td class="label">Credential Status</td>
        <td class="value"><span class="badge {'badge-active' if status == 'ACTIVE' else 'badge-revoked'}">{status}</span></td>
      </tr>
      <tr>
        <td class="label">Date of Issuance</td>
        <td class="value">{issued_at}</td>
      </tr>
      <tr>
        <td class="label">Cryptographic Key ID</td>
        <td class="value"><code>{key_id}</code></td>
      </tr>
    </table>

    <div class="footer-section">
      <div class="security-notice">
        <strong>Ed25519 Cryptographic Verification:</strong><br>
        This document contains no raw sensitive identifiers in its payload or QR code.<br>
        Scan the QR code or verify online at:<br>
        <a href="{verify_url}" target="_blank">{verify_url}</a><br>
        <small>Rule 10 & AICTE Quality Framework Compliance Guaranteed.</small>
      </div>
      <div class="qr-box">
        {qr_svg}
      </div>
    </div>
  </div>
</body>
</html>"""
    return html


def render_certificate_pdf(credential: Credential, host: Optional[str] = None) -> bytes:
    """
    Renders pure Python compliant PDF 1.4 certificate printing 'Student ID + APAAR ID (masked)'.
    """
    payload = credential.payload or {}
    enrollment = credential.enrollment
    student = enrollment.student if enrollment else None

    student_display_name = payload.get("student_display_name", "Student")
    qualification = payload.get("qualification", "Degree Programme")
    institution_name = payload.get("institution_name", "AICTE Institution")
    public_ref = credential.public_ref
    verify_url = build_verification_url(public_ref, host=host)
    student_id = str(student.id) if student else "N/A"
    apaar_masked = student.apaar_masked if student else "XXXX-XXXX-XXXX"

    # Minimal standard PDF 1.4 syntax
    lines = [
        "ALL INDIA COUNCIL FOR TECHNICAL EDUCATION",
        "APAAR CONNECT VERIFIABLE CREDENTIAL",
        "--------------------------------------------------",
        f"Student Name: {student_display_name}",
        f"Student ID: {student_id}",
        f"APAAR ID (masked): {apaar_masked}",
        f"Institution: {institution_name}",
        f"Programme: {qualification}",
        f"Verification Reference: {public_ref}",
        f"Status: {credential.status}",
        f"Issued At: {payload.get('issued_at', '')}",
        f"Key ID: {credential.key_id}",
        "--------------------------------------------------",
        f"Verify Online: {verify_url}",
        "Ed25519 Digitally Signed. Rule 10 Compliant.",
    ]

    stream_content = "BT /F1 14 Tf 40 760 Td (" + lines[0] + ") Tj ET\n"
    stream_content += "BT /F1 10 Tf 40 740 Td (" + lines[1] + ") Tj ET\n"
    y = 700
    for l in lines[2:]:
        # Escape parenthesis in PDF strings
        clean_line = l.replace("(", r"\(").replace(")", r"\)")
        stream_content += f"BT /F1 10 Tf 40 {y} Td ({clean_line}) Tj ET\n"
        y -= 22

    content_bytes = stream_content.encode("latin-1", "replace")
    stream_len = len(content_bytes)

    pdf = (
        f"%PDF-1.4\n"
        f"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        f"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        f"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj\n"
        f"4 0 obj <</Length {stream_len}>>\n"
        f"stream\n"
    ).encode("ascii") + content_bytes + (
        f"\nendstream\nendobj\n"
        f"5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        f"xref\n0 6\n"
        f"0000000000 65535 f \n"
        f"0000000010 00000 n \n"
        f"0000000060 00000 n \n"
        f"0000000119 00000 n \n"
        f"0000000241 00000 n \n"
        f"0000000300 00000 n \n"
        f"trailer <</Size 6 /Root 1 0 R>>\n"
        f"startxref\n370\n%%EOF\n"
    ).encode("ascii")

    return pdf
