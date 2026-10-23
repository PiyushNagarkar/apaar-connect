# APAAR Connect - System Architecture

> **NOTICE:** All data is synthetic. Simulated APAAR service (`MOCK_APAAR_V1`). Never integrated with real APAAR/DigiLocker production services.

---

## 1. High-Level Architecture Overview

APAAR Connect is architected as a **modular monolith** designed for AICTE (All India Council for Technical Education) to perform automated, privacy-preserving, 3-layer verification of student admissions.

```
+--------------------------------------------------------------------------------+
|                               Frontend (Vite + React)                          |
|   - Role-based Portal (AICTE Admin, Reviewer, Institution Admin, Auditor)      |
|   - Multi-layer Verification Visualizer (L1, L2, L3)                           |
|   - Triage & Review Queue with Priority Scoring                                |
|   - Verifiable QR Credential Presenter & Scanner                               |
|   - Synthetic Data Banner ("Synthetic data. Simulated APAAR service.")         |
+---------------------------------------+----------------------------------------+
                                        | HTTP / JSON (X-Request-ID Header)
                                        v
+--------------------------------------------------------------------------------+
|                           Backend (FastAPI Monolith)                           |
|                                                                                |
|  +-----------------------+  +----------------------+  +---------------------+  |
|  | RequestIdMiddleware   |  | Structured Errors    |  | Role-Based Auth     |  |
|  +-----------------------+  +----------------------+  +---------------------+  |
|                                                                                |
|  +--------------------------------------------------------------------------+  |
|  |                     3-Layer Verification Engine                          |  |
|  |                                                                          |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |  | Layer 1: Identity Verification (Adapter: MOCK_APAAR_V1)            |  |  |
|  |  | - APAAR existence check, name & DOB fuzzy match                       |  |  |
|  |  | - Retry queue on timeout/unavailability; never auto-fails          |  |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |                                                                          |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |  | Layer 2: Institutional Authority Verification                         |  |  |
|  |  | - Program approval snapshot frozen by AICTE                         |  |  |
|  |  | - Status validation: FROZEN only; rejected if DRAFT/UNAPPROVED      |  |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |                                                                          |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |  | Layer 3: Admission & Seat Compliance Verification                    |  |  |
|  |  | - Per-category quota enforcement (REGULAR, NRI, SUPERNUMERARY, etc)|  |  |
|  |  | - Deterministic blind-index duplicate candidate detection           |  |  |
|  |  | - Never auto-accuses; generates human review cases                 |  |  |
|  |  +--------------------------------------------------------------------+  |  |
|  |                                                                          |  |
|  |  Record is VERIFIED only if L1, L2, and L3 all PASS                      |  |
|  +--------------------------------------------------------------------------+  |
|                                                                                |
|  +-----------------------+  +----------------------+  +---------------------+  |
|  | Verifiable Credential |  | Audit Trail Service  |  | Versioning Service  |  |
|  | Issuance & QR Signing |  | Tamper-evident Hash  |  | Snapshot on Update  |  |
|  +-----------------------+  +----------------------+  +---------------------+  |
+---------------------------------------+----------------------------------------+
                                        | SQLAlchemy ORM
                                        v
+--------------------------------------------------------------------------------+
|                         PostgreSQL 16 Relational Store                         |
|   15 Core Models with UUIDv4 PKs, UTC Timestamps, Indexes & DB Constraints    |
+--------------------------------------------------------------------------------+
```

---

## 2. 3-Layer Verification Pipeline

1. **Layer 1: Identity (MOCK_APAAR_V1)**
   - Communicates with simulated APAAR adapter labeled `MOCK_APAAR_V1` via abstract `IdentityProvider` interface and factory `get_identity_provider()`.
   - **Deterministic Validation & Luhn Algorithm**: Validates 12-digit format with mod-10 Luhn check. Unchecked fields return SQL `NULL` (`None`) instead of fake booleans.
   - **Name Normalization & Similarity**: Collapses whitespace, strips titles (`Mr.`, `Dr.`), and matches via token sets and sequence ratio ($\ge 0.85$), e.g. `"Aarav  Sharma"` ~ `"AARAV SHARMA"`.
   - **Status Paths**:
     - `PASSED`: In synthetic registry with matching name and DOB.
     - `NOT_PROVIDED`: APAAR omitted; fields are `null`.
     - `FAILED(FORMAT)`: Bad length or invalid Luhn checksum; exists is `false`, demographics `null`.
     - `FAILED(NOT_FOUND)`: Valid format but not in synthetic registry; exists is `false`.
     - `FAILED(MISMATCH)`: In registry but name or DOB mismatch with per-field booleans.
     - `PENDING`: Async simulation triggered by magic ID suffix `888` or env toggle.
     - `UNAVAILABLE`: Downstream gateway timeout simulation triggered by magic ID suffix `999` or env toggle.
   - **Exponential Backoff**: Simulates retries on `UNAVAILABLE` with configurable multipliers.
   - **Policy Engine**:
     - `UNAVAILABLE` never marks records failed or verified; guarantees `PROVISIONAL` lifecycle.
     - `NOT_PROVIDED` allows `PROVISIONAL` status during an active grace period ($N$ days, default 30), escalating to `ERROR` once expired.
   - **Privacy Guarantee (Rule 10)**: Never logs full APAAR numbers (masked as `XXXX-XXXX-1234`).

2. **Layer 2: Institutional Authority**
   - Validates that the admitting institution holds a frozen, approved seat matrix for the academic year and programme branch.
   - Rejects unapproved programs or admissions submitted against draft / unratified approvals.

3. **Layer 3: Seat Compliance & Duplicate Resolution**
   - Verifies that admissions do not exceed approved caps for regular, NRI, or supernumerary quotas.
   - Detects cross-institution or duplicate enrollments via keyed HMAC-SHA256 blind indices.
   - Sends boundary cases and duplicates to human review queues with explicit priority components and explanation codes.

---

## 3. Privacy & Security Architecture (Rule 10)

- **AES-256-GCM Encryption**: Raw APAAR IDs are encrypted immediately upon ingestion.
- **Keyed Blind Index (HMAC-SHA256)**: Fast lookup for duplicate detection without ever decrypting student APAAR numbers in bulk.
- **Masked Display**: Only `XXXX-XXXX-1234` is ever rendered in logs, UI, and exports.
- **Verifiable Credentials**: Signed using Ed25519 / HMAC with canonical payload; contains zero raw APAAR data.

---

## 4. Tamper-Evident Audit Logging (Rule 9)

- Every mutation writes an `AuditEvent` recording `(actor_id, action, entity_type, entity_id, reason, request_id, timestamp)`.
- Each event includes a SHA-256 cryptographic hash chained to the previous event's hash (`prev_hash`).
