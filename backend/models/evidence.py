from sqlalchemy import Column, String, Integer, DateTime, Text, JSON
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class EvidenceRecord(Base, TimestampedUUIDMixin):
    """
    evidence_records(reference, sha256_hash, evidence_type, uploader_id, filename,
      mime_type, file_size_bytes, storage_path, storage_provider, virus_scan_status,
      virus_scan_report, metadata_json)
    Evidence types: IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION.
    Stores cryptographically validated SHA-256 hash and metadata for uploaded documents.
    """
    __tablename__ = "evidence_records"

    reference = Column(String(128), nullable=False, index=True)  # Associated record reference (enrollment_id, student_id, etc.)
    sha256_hash = Column(String(64), nullable=False, index=True) # Cryptographic SHA-256 checksum
    evidence_type = Column(String(32), nullable=False, index=True) # IDENTITY, APPROVAL, ADMISSION_CATEGORY, COMPLETION
    uploader_id = Column(String(64), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String(512), nullable=False)
    storage_provider = Column(String(32), default="LOCAL", nullable=False)  # LOCAL, MINIO, S3
    virus_scan_status = Column(String(32), default="CLEAN", nullable=False) # CLEAN, INFECTED, PENDING
    virus_scan_report = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
