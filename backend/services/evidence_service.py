"""
Evidence Service (backend/services/evidence_service.py).

Implements:
1. Registration & Upload of Evidence files (reference + SHA-256 + type + uploader).
   Types: IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION.
2. Local / Object storage adapter with directory isolation.
3. Access-controlled signed download URLs with HMAC token & expiry timestamp.
4. File size & MIME type limits (max 10MB, PDF/PNG/JPEG).
5. Stub virus scan hook scanning for test signatures and suspicious executables.
"""
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.models.evidence import EvidenceRecord
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.services.audit import record_audit_event

logger = logging.getLogger("evidence_service")

ALLOWED_EVIDENCE_TYPES = {
    "IDENTITY",
    "APPROVAL",
    "ADMISSION_CATEGORY",
    "COMPLETION",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}

EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
SIGNING_SECRET = os.getenv("EVIDENCE_URL_SECRET", "aicte_evidence_hmac_secret_key_2025")
STORAGE_DIR = os.getenv("EVIDENCE_STORAGE_DIR", os.path.join(os.path.abspath("."), "uploads", "evidence"))


# ---------------------------------------------------------------------------
# Stub Virus Scan Hook
# ---------------------------------------------------------------------------
def scan_file_for_viruses(file_bytes: bytes, filename: str) -> Tuple[bool, str]:
    """
    Stub antivirus scanner hook.
    Detects standard EICAR test string and forbidden binary headers.
    Returns (is_clean: bool, scan_report: str).
    """
    if EICAR_SIGNATURE in file_bytes:
        return False, "VIRUS_DETECTED: EICAR test signature identified in file payload."

    # Prevent disguised executable files (.exe, .dll, .bat, ELF)
    if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
        return False, "MALWARE_DETECTED: Executable binary header found in document file."

    return True, "CLEAN: Antivirus engine AICTE-STUB-SCAN-V1 passed with zero threats."


# ---------------------------------------------------------------------------
# Access-Controlled Signed Download URLs
# ---------------------------------------------------------------------------
def generate_signed_download_url(
    evidence_id: str,
    expires_in_seconds: int = 3600,
    base_url: Optional[str] = None,
) -> str:
    """Generates an HMAC-signed URL with expiry for secure, time-limited document download."""
    expires_at = int(time.time()) + expires_in_seconds
    msg = f"{evidence_id}:{expires_at}".encode("utf-8")
    token = hmac.new(SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    prefix = base_url.rstrip("/") if base_url else ""
    return f"{prefix}/api/evidence/{evidence_id}/download?token={token}&expires={expires_at}"


def verify_signed_download_token(evidence_id: str, token: str, expires: int) -> bool:
    """Validates the HMAC-signed URL token and expiry timestamp."""
    now = int(time.time())
    if now > expires:
        logger.warning(f"Signed URL for evidence '{evidence_id}' has expired (exp: {expires}, now: {now})")
        return False

    msg = f"{evidence_id}:{expires}".encode("utf-8")
    expected_token = hmac.new(SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_token, token)


# ---------------------------------------------------------------------------
# Storage & Evidence Registration
# ---------------------------------------------------------------------------
def store_evidence_file(
    db: Session,
    reference: str,
    evidence_type: str,
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
    uploader_id: str = "SYSTEM",
    metadata_json: Optional[Dict[str, Any]] = None,
) -> EvidenceRecord:
    """
    Validates, virus-scans, hashes with SHA-256, and stores an evidence document:
    - Type must be IDENTITY, APPROVAL, ADMISSION_CATEGORY, or COMPLETION.
    - Size <= 10MB.
    - Safe MIME types.
    """
    clean_type = evidence_type.strip().upper()
    if clean_type not in ALLOWED_EVIDENCE_TYPES:
        raise BadRequestError(
            f"Invalid evidence type '{evidence_type}'. Must be one of {sorted(list(ALLOWED_EVIDENCE_TYPES))}."
        )

    # 1. Size limit check
    file_size = len(file_bytes)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise BadRequestError(
            f"File exceeds maximum size limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB (Actual: {file_size} bytes)."
        )

    # 2. MIME type check
    effective_mime = (mime_type or "application/pdf").lower()
    if effective_mime not in ALLOWED_MIME_TYPES:
        raise BadRequestError(
            f"MIME type '{effective_mime}' is not permitted. Allowed: {sorted(list(ALLOWED_MIME_TYPES))}."
        )

    # 3. Virus Scan Hook
    is_clean, scan_report = scan_file_for_viruses(file_bytes, filename)
    if not is_clean:
        logger.error(f"Virus scan failed for file '{filename}': {scan_report}")
        raise BadRequestError(f"Security scan rejected file: {scan_report}")

    # 4. Compute SHA-256 Checksum
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # 5. Persist file bytes to local storage
    os.makedirs(STORAGE_DIR, exist_ok=True)
    _, ext = os.path.splitext(filename)
    safe_filename = f"{sha256_hash}{ext or '.bin'}"
    target_path = os.path.join(STORAGE_DIR, safe_filename)

    with open(target_path, "wb") as f:
        f.write(file_bytes)

    # 6. Persist EvidenceRecord in DB
    record = EvidenceRecord(
        reference=reference.strip(),
        sha256_hash=sha256_hash,
        evidence_type=clean_type,
        uploader_id=uploader_id,
        filename=os.path.basename(filename),
        mime_type=effective_mime,
        file_size_bytes=file_size,
        storage_path=target_path,
        storage_provider="LOCAL",
        virus_scan_status="CLEAN" if is_clean else "INFECTED",
        virus_scan_report=scan_report,
        metadata_json=metadata_json or {},
    )
    db.add(record)

    # 7. Audit Event
    record_audit_event(
        db=db,
        actor_id=uploader_id,
        action="EVIDENCE_UPLOADED",
        entity_type="EVIDENCE",
        entity_id=str(record.id),
        reason=f"Uploaded evidence '{record.filename}' type '{clean_type}' (SHA-256: {sha256_hash})",
    )
    db.flush()

    logger.info(f"Registered evidence '{record.id}' type '{clean_type}' ref '{reference}' (SHA-256: {sha256_hash})")
    return record


def get_evidence_by_id(db: Session, evidence_id: str) -> Optional[EvidenceRecord]:
    """Retrieves an evidence record by ID."""
    return db.query(EvidenceRecord).filter(EvidenceRecord.id == evidence_id).first()


def list_evidence(
    db: Session,
    reference: Optional[str] = None,
    evidence_type: Optional[str] = None,
    uploader_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[EvidenceRecord]:
    """Queries evidence records by reference, type, or uploader."""
    q = db.query(EvidenceRecord)
    if reference:
        q = q.filter(EvidenceRecord.reference == reference.strip())
    if evidence_type:
        q = q.filter(EvidenceRecord.evidence_type == evidence_type.strip().upper())
    if uploader_id:
        q = q.filter(EvidenceRecord.uploader_id == uploader_id)

    return q.order_by(EvidenceRecord.created_at.desc()).offset(offset).limit(limit).all()
