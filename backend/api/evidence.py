"""
Evidence Management API Endpoints (backend/api/evidence.py).

Implements:
- POST /api/evidence: Upload/register evidence document (IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION).
- GET /api/evidence: Query evidence records by reference, type, uploader.
- GET /api/evidence/{id}: Get metadata and fresh signed download URL.
- GET /api/evidence/{id}/download: Secure file download validating HMAC token and expiry timestamp.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os

from backend.database import get_db
from backend.models.evidence import EvidenceRecord
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.schemas.privacy_evidence_audit import EvidenceRegisterRequest, EvidenceResponse
from backend.security.authz import (
    get_current_user,
    require_authenticated_user,
    require_roles,
    UserPrincipal,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
)
from backend.services.evidence_service import (
    ALLOWED_EVIDENCE_TYPES,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    generate_signed_download_url,
    get_evidence_by_id,
    list_evidence,
    store_evidence_file,
    verify_signed_download_token,
)
from backend.services.privacy_service import log_access_event

router = APIRouter(prefix="/evidence", tags=["Evidence"])


def _extract_base_url(request: Request) -> str:
    """Extracts client base URL."""
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}"
    return str(request.base_url).rstrip("/")


@router.post(
    "",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register & upload an evidence document",
)
async def upload_evidence_endpoint(
    request: Request,
    reference: str = Form(..., description="Reference ID (e.g. enrollment, approval, student UUID)"),
    evidence_type: str = Form(..., description="IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION"),
    file: UploadFile = File(..., description="Binary document or image file"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Uploads and registers an evidence file:
    - Calculates cryptographic SHA-256 checksum.
    - Runs stub antivirus scan (rejects viruses/disguised binaries).
    - Checks file size (<= 10MB) and MIME type.
    - Persists file and returns metadata with HMAC signed download URL.
    """
    file_bytes = await file.read()
    filename = file.filename or "evidence.bin"
    mime_type = file.content_type or "application/octet-stream"

    record = store_evidence_file(
        db=db,
        reference=reference,
        evidence_type=evidence_type,
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        uploader_id=user.user_id,
    )
    db.commit()

    base_url = _extract_base_url(request)
    signed_url = generate_signed_download_url(str(record.id), expires_in_seconds=3600, base_url=base_url)

    return EvidenceResponse(
        id=str(record.id),
        reference=record.reference,
        sha256_hash=record.sha256_hash,
        evidence_type=record.evidence_type,
        uploader_id=record.uploader_id,
        filename=record.filename,
        mime_type=record.mime_type,
        file_size_bytes=record.file_size_bytes,
        virus_scan_status=record.virus_scan_status,
        virus_scan_report=record.virus_scan_report,
        signed_download_url=signed_url,
        created_at=record.created_at,
    )


@router.get(
    "",
    response_model=List[EvidenceResponse],
    summary="List evidence records with filters",
)
def list_evidence_endpoint(
    request: Request,
    reference: Optional[str] = Query(None, description="Filter by associated reference"),
    evidence_type: Optional[str] = Query(None, description="IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION"),
    uploader_id: Optional[str] = Query(None, description="Filter by uploader ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """Queries evidence records with filter support and generates signed download URLs."""
    records = list_evidence(
        db=db,
        reference=reference,
        evidence_type=evidence_type,
        uploader_id=uploader_id,
        limit=limit,
        offset=offset,
    )
    base_url = _extract_base_url(request)

    # Log access event for evidence audit
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_access_event(
        db=db,
        actor_id=user.user_id,
        actor_role=user.role,
        record_type="EVIDENCE_LIST",
        record_id=reference or "ALL",
        purpose="AUDIT_VERIFICATION",
        fields_accessed=["reference", "evidence_type", "sha256_hash", "filename"],
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.commit()

    return [
        EvidenceResponse(
            id=str(r.id),
            reference=r.reference,
            sha256_hash=r.sha256_hash,
            evidence_type=r.evidence_type,
            uploader_id=r.uploader_id,
            filename=r.filename,
            mime_type=r.mime_type,
            file_size_bytes=r.file_size_bytes,
            virus_scan_status=r.virus_scan_status,
            virus_scan_report=r.virus_scan_report,
            signed_download_url=generate_signed_download_url(str(r.id), expires_in_seconds=3600, base_url=base_url),
            created_at=r.created_at,
        )
        for r in records
    ]


@router.get(
    "/{evidence_id}",
    response_model=EvidenceResponse,
    summary="Get evidence metadata and signed download URL",
)
def get_evidence_endpoint(
    evidence_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """Retrieves specific evidence metadata and generates a fresh signed URL."""
    rec = get_evidence_by_id(db, evidence_id)
    if not rec:
        raise NotFoundError("Evidence record not found.")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_access_event(
        db=db,
        actor_id=user.user_id,
        actor_role=user.role,
        record_type="EVIDENCE",
        record_id=evidence_id,
        purpose="AUDIT_INSPECTION",
        fields_accessed=["filename", "sha256_hash", "storage_path", "evidence_type"],
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.commit()

    base_url = _extract_base_url(request)
    return EvidenceResponse(
        id=str(rec.id),
        reference=rec.reference,
        sha256_hash=rec.sha256_hash,
        evidence_type=rec.evidence_type,
        uploader_id=rec.uploader_id,
        filename=rec.filename,
        mime_type=rec.mime_type,
        file_size_bytes=rec.file_size_bytes,
        virus_scan_status=rec.virus_scan_status,
        virus_scan_report=rec.virus_scan_report,
        signed_download_url=generate_signed_download_url(str(rec.id), expires_in_seconds=3600, base_url=base_url),
        created_at=rec.created_at,
    )


@router.get(
    "/{evidence_id}/download",
    summary="Download evidence file with HMAC signed URL validation",
)
def download_evidence_endpoint(
    evidence_id: str,
    token: str = Query(..., description="HMAC-SHA256 signature token"),
    expires: int = Query(..., description="Expiration epoch timestamp"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Serves stored evidence file only if signed token is valid and unexpired.
    Does not require standard session header if signed URL is valid (supports direct browser download).
    """
    if not verify_signed_download_token(evidence_id, token, expires):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired signed download URL token.",
        )

    rec = get_evidence_by_id(db, evidence_id)
    if not rec:
        raise NotFoundError("Evidence record not found.")

    if not os.path.exists(rec.storage_path):
        raise NotFoundError("Evidence file is not present on storage volume.")

    # Log access event for the download
    client_ip = request.client.host if (request and request.client) else None
    user_agent = request.headers.get("user-agent") if request else None
    log_access_event(
        db=db,
        actor_id="SIGNED_URL_RECIPIENT",
        actor_role="VERIFIER",
        record_type="EVIDENCE_FILE",
        record_id=evidence_id,
        purpose="SECURE_DOCUMENT_DOWNLOAD",
        fields_accessed=["file_bytes"],
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.commit()

    return FileResponse(
        path=rec.storage_path,
        media_type=rec.mime_type,
        filename=rec.filename,
    )
