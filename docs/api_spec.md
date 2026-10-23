# APAAR Connect - API Specification

## Base URL
All API endpoints are hosted under `/api`.

---

## 1. Health & Status

### `GET /api/health`
Health check endpoint.
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "mock_adapter": "MOCK_APAAR_V1",
  "synthetic": true,
  "service": "APAAR Connect Backend",
  "version": "1.0.0"
}
```

---

## 2. Structured Error Format (Rule 12)

Every API error follows this JSON structure:

```json
{
  "code": "ERROR_CODE_STRING",
  "message": "Human-readable explanation of error.",
  "field": "optional_field_name",
  "details": {
    "key": "value"
  }
}
```

### HTTP Status Code Conventions
- `400 Bad Request`: Input validation failed or invalid parameters.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: Cross-institution scope violation (Rule 7) or insufficient permissions.
- `404 Not Found`: Entity not found.
- `409 Conflict`: **Invalid lifecycle state transitions** (Rule 12) or duplicate unique key collision.
- `422 Unprocessable Entity`: Pydantic schema validation failures.
- `500 Internal Server Error`: Unexpected server exceptions.

---

## 3. Tracing Middleware
All requests accept an optional `X-Request-ID` header. If absent, the backend assigns a unique `req-<uuid>` and returns it in the response header `X-Request-ID`. All audit events, identity checks, and error logs reference this identifier for end-to-end auditability (Rule 9).

---

## 4. Identity Adapter Endpoints (L1 Verification - MOCK_APAAR_V1)

### `POST /api/identity/verify`
Executes simulated identity verification against `MOCK_APAAR_V1` and persists the check to `identity_checks`. Full APAAR numbers are never logged (always masked as `XXXX-XXXX-1234`).

- **Request Body**:
```json
{
  "request_id": "optional-custom-request-id",
  "student_id": "optional-student-uuid",
  "apaar_id": "987654321015",
  "student_name": "Priya Patel",
  "date_of_birth": "2005-03-21",
  "consent_reference": "CONSENT-REF-2026-001"
}
```

- **Response `200 OK`**:
```json
{
  "check_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "request_id": "req-123456789abc",
  "source": "MOCK_APAAR_V1",
  "status": "PASSED",
  "exists": true,
  "name_match": true,
  "dob_match": true,
  "checked_at": "2026-10-23T01:50:00Z",
  "reason_code": "MATCH_CONFIRMED",
  "raw_details": {
    "gender": "FEMALE",
    "simulated": true
  }
}
```

### `GET /api/identity/checks/{id}`
Retrieves a previously stored identity verification check by its check ID.

- **Response `200 OK`**:
```json
{
  "check_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "student_id": "uuid-or-null",
  "request_id": "req-123456789abc",
  "source": "MOCK_APAAR_V1",
  "status": "PASSED",
  "exists": true,
  "name_match": true,
  "dob_match": true,
  "created_at": "2026-10-23T01:50:00Z",
  "raw": {
    "apaar_masked": "XXXX-XXXX-1015",
    "reason_code": "MATCH_CONFIRMED",
    "consent_reference": "CONSENT-REF-2026-001"
  }
}
```

### `GET /api/students/{id}/identity-checks`
Retrieves all historical identity checks linked to a given student record.

- **Response `200 OK`**:
```json
{
  "student_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "total_checks": 2,
  "checks": [
    {
      "check_id": "...",
      "request_id": "...",
      "source": "MOCK_APAAR_V1",
      "status": "PASSED",
      "exists": true,
      "name_match": true,
      "dob_match": true,
      "created_at": "2026-10-23T01:50:00Z",
      "raw": { "apaar_masked": "XXXX-XXXX-1015" }
    }
  ]
}
```

---

## 5. Submission Pipeline Endpoints (`/api/submissions`)

### `POST /api/submissions`
Initializes a new admission batch submission. Supports idempotency via `idempotency_key`.

- **Request Body**:
```json
{
  "institution_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "academic_year": "2024-2025",
  "programme": "ENGINEERING_AND_TECHNOLOGY",
  "round": "ROUND_1",
  "idempotency_key": "unique-client-key-123"
}
```

### `POST /api/submissions/{id}/upload`
Uploads and parses a CSV batch file.
- Enforces 10MB size limit.
- Safe parsing with UTF-8 / BOM (`utf-8-sig`) handling.
- Formula injection sanitization for cells starting with `=`, `+`, `-`, `@`.
- Demographic normalization: whitespace collapsed, names case-folded, DOB to ISO YYYY-MM-DD, mobile to last 10 digits.

### `POST /api/submissions/{id}/validate` (DRY RUN)
Dry run validation against required fields, cross-field rules, L1 identity preview, L2 authority preview (frozen approval check), and L3 seat capacity preview.
- **CRITICAL SEMANTICS**: Writes NOTHING except validation results; reserves NO seats.

### `GET /api/submissions/{id}/errors`
Returns structured per-row errors:
```json
[
  {
    "row_number": 2,
    "field": "seat_type",
    "error_code": "NRI_SEAT_FLAG_MISMATCH",
    "explanation": "Admissions under NRI seat quota require nri_flag to be set to true.",
    "suggested_fix": "Set nri_flag to true or select REGULAR seat type."
  }
]
```

### `GET /api/submissions/{id}/rows`
Returns paginated submission rows with optional outcome filter (`VALID`, `INVALID`, `COMMITTED`, `FAILED`, `UNPROCESSED`).

### `POST /api/submissions/{id}/commit`
Commits admission records using the CURRENT frozen approval.
- **Per row, ONE database transaction**:
  - Locks the `seat_allocation` row (`SELECT ... FOR UPDATE`).
  - Rechecks capacity.
  - Inserts student and enrollment.
  - Writes `RecordVersion` and `AuditEvent`.
- **Concurrency Guarantee**: Two concurrent commits for the last seat: exactly one succeeds.
- Reports outcomes separately: `COMMITTED`, `FAILED`, `UNPROCESSED`.
- If the submission round is locked, requires a mandatory `reason_code` (`DATA_ENTRY_ERROR`, `OFFICIAL_CORRECTION`, `TRANSFER_UPDATE`, `WITHDRAWAL_UPDATE`, `APPROVAL_UPDATE`, `OTHER_REQUIRES_EXPLANATION`) and tags records as late.

### `POST /api/submissions/{id}/retry`
Idempotent retry for `FAILED` or `UNPROCESSED` rows. Retrying never double-inserts due to deterministic `row_key`.

### `GET /api/submissions/{id}/report`
Downloads results report as a CSV file (`row_number, apaar_masked, name, programme, branch, seat_type, category, outcome, errors`).

---

## 6. Single Student Admission Entry (`POST /api/students`)

Uses the exact same underlying validation, row locking (`SELECT ... FOR UPDATE`), capacity enforcement, RecordVersion snapshot, and AuditEvent logging.

- **Request Body**:
```json
{
  "institution_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "apaar_id": "987654321015",
  "name": "Priya Patel",
  "dob": "2005-03-21",
  "gender": "FEMALE",
  "mobile": "9876543210",
  "email": "priya@example.com",
  "roll_no": "R101",
  "programme": "ENGINEERING_AND_TECHNOLOGY",
  "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
  "academic_year": "2024-2025",
  "seat_type": "REGULAR",
  "category": "OPEN",
  "admission_date": "2024-08-01",
  "consent_reference": "CONSENT-01"
}
```

- **Response `201 Created`**:
```json
{
  "student_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "enrollment_id": "7ca85f64-5717-4562-b3fc-2c963f66afa7",
  "name": "Priya Patel",
  "apaar_masked": "XXXX-XXXX-1015",
  "programme": "ENGINEERING_AND_TECHNOLOGY",
  "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
  "seat_type": "REGULAR",
```

---

## 7. Multi-Layer Compliance & Verification Endpoints

### `GET /api/enrollments/{id}/compliance`
Shows detailed inputs, outputs, rule evaluations, and overall verification verdict across all three verification layers:
- **L1 Identity**: APAAR demographic match, format check, and simulated gateway status.
- **L2 Authority**: Frozen approval order reference, campus/shift snapshot validation.
- **L3 Compliance**: Per-category seat quota, capacity utilization, and citizenship flag reconciliation.

- **Response `200 OK`**:
```json
{
  "enrollment_id": "7ca85f64-5717-4562-b3fc-2c963f66afa7",
  "record_ref": "7ca85f64-5717-4562-b3fc-2c963f66afa7",
  "overall_verdict": "VERIFIED | BLOCKED_ERROR | UNDER_REVIEW | PROVISIONAL",
  "verified": true,
  "requires_review": false,
  "blocks_commit": false,
  "l1_identity": {
    "layer": "L1_IDENTITY",
    "status": "PASSED",
    "inputs": { "apaar_id_provided": true, "student_name": "Priya Patel", "date_of_birth": "2005-03-21" },
    "outputs": { "status": "PASSED", "issues_count": 0 },
    "issues": []
  },
  "l2_authority": {
    "layer": "L2_AUTHORITY",
    "status": "PASSED",
    "inputs": { "institution_id": "...", "programme": "...", "branch": "...", "academic_year": "2024-2025" },
    "outputs": { "approval_ref": "EOA-2024-001", "approval_status": "FROZEN" },
    "issues": []
  },
  "l3_compliance": {
    "layer": "L3_COMPLIANCE",
    "status": "PASSED",
    "inputs": { "seat_type": "REGULAR", "category": "OPEN" },
    "outputs": {
      "seat_compliance": { "approved": 120, "confirmed": 100, "active": 20, "occupied": 120, "available": 0, "status": "AT_LIMIT" }
    },
    "issues": []
  },
  "all_issues": []
}
```

### `POST /api/enrollments/{id}/recheck`
Re-runs all three layer validation rules against the current database state.
- If verified: sets status to `CONFIRMED` and `verified = true`.
- If `REGULATORY_ALERT` or `HIGH`: sets status to `UNDER_REVIEW`, `verified = false`, and opens an AICTE `ReviewCase`.
- If `ERROR`: sets status to `PROVISIONAL` and `verified = false`.
- Records a cryptographic `AuditEvent` linking to the audit chain.

---

## 8. Duplicate Detection & Candidate Generator Endpoints

Duplicate detection is implemented as a candidate generator and weighted feature scorer:
$$\text{score} = 0.5 \times \text{apaar\_exact} + 0.2 \times \text{dob\_equal} + 0.15 \times \text{mobile\_equal} + 0.15 \times \text{name\_similarity}$$

### Tiers & Actions
1. `CRITICAL`: Same `apaar_hash` active across two different institutions $\to$ opens review case, priority 95.
2. `HIGH`: Same `apaar_hash` twice within one institution or batch $\to$ blocks second row commit, sets `UNDER_REVIEW`, priority 85.
3. `MEDIUM`: Same normalised name + DOB + 10-digit mobile (no APAAR match) $\to$ opens review case, priority 65.
4. `FUZZY`: Name similarity (Jaro-Winkler $\ge 0.92$) and exact same DOB $\to$ opens review case, priority 50.
   - *Regulatory Invariant*: Name similarity with a different DOB produces **NO alert**.
   - *Regulatory Invariant*: Twins with same DOB and different first names produce **NO alert**.
5. `PROGRESSION`: Same `apaar_hash` where earlier enrollment is `COMPLETED` $\to$ logged as normal academic progression, **no case opened**.

### `POST /api/duplicates/check`
Candidate generator and scorer endpoint. Evaluates an admission record against the active database using candidate blocking (indexed on `dob`, `mobile_last10`, and `apaar_hash`).

- **Request Body**:
```json
{
  "enrollment_id": "optional-enrollment-uuid",
  "apaar_id": "987654321015",
  "name": "Priya Patel",
  "dob": "2005-03-21",
  "mobile": "9876543210",
  "email": "priya.patel@example.com",
  "institution_id": "INST-001",
  "academic_year": "2024-2025",
  "save_candidates": false
}
```

- **Response `200 OK`**:
```json
{
  "total_matches": 1,
  "highest_tier": "CRITICAL",
  "has_critical": true,
  "has_high": false,
  "matches": [
    {
      "match_type": "CRITICAL",
      "score": 0.95,
      "reasons": [
        "APAAR_EXACT_MATCH",
        "DOB_EXACT_MATCH",
        "MOBILE_EXACT_MATCH",
        "NAME_EXACT_MATCH",
        "CROSS_INSTITUTION_ACTIVE"
      ],
      "enrollment_a": "uuid-first-enrollment",
      "enrollment_b": "uuid-second-enrollment",
      "requires_case": true,
      "is_progression": false,
      "details": {
        "explanation": "Same APAAR hash is actively enrolled in two different institutions: 'INST-001' and 'INST-002'.",
        "institution_a": "INST-001",
        "institution_b": "INST-002"
      }
    }
  ]
}
```

### `GET /api/duplicates/candidates`
Returns detected duplicate candidate pairs with enrollment and student metadata. Enforces institutional scoping (institution users can only access candidate pairs involving their own institution).

- **Query Parameters**:
  - `status`: `DETECTED` | `UNDER_REVIEW` | `RESOLVED` | `DISMISSED` | `LOGGED_PROGRESSION`
  - `match_type`: `CRITICAL` | `HIGH` | `MEDIUM` | `FUZZY` | `PROGRESSION`
  - `min_score`: float filter between `0.0` and `1.0`
  - `institution_id`: target institution UUID (AICTE Central only)
  - `limit`: page size (default 50)
  - `offset`: page offset (default 0)

- **Response `200 OK`**:
```json
{
  "items": [
    {
      "id": "candidate-uuid",
      "match_type": "CRITICAL",
      "score": 0.95,
      "reasons": ["APAAR_EXACT_MATCH", "CROSS_INSTITUTION_ACTIVE"],
      "status": "DETECTED",
      "created_at": "2026-10-23T02:40:00Z",
      "enrollment_a": {
        "enrollment_id": "enroll-1",
        "institution_id": "inst-1",
        "institution_name": "Delhi Technical Institute",
        "academic_year": "2024-2025",
        "status": "CONFIRMED",
        "student_name": "Priya Patel",
        "student_dob": "2005-03-21",
        "apaar_masked": "XXXX-XXXX-1015"
      },
      "enrollment_b": {
        "enrollment_id": "enroll-2",
        "institution_id": "inst-2",
        "institution_name": "Mumbai Institute of Tech",
        "academic_year": "2024-2025",
        "status": "ACTIVE",
        "student_name": "Priya Patel",
        "student_dob": "2005-03-21",
        "apaar_masked": "XXXX-XXXX-1015"
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## 9. Admission Lifecycle & Single-Source-of-Truth State Machine

Implemented centrally in `services/lifecycle.py`, governing all enrollment status updates across the application. Any invalid transition returns HTTP `409 Conflict` with a structured payload `{code: "INVALID_TRANSITION", from, to, allowed: [...]}`.

### `PATCH /api/enrollments/{id}/status`
Transitions an enrollment record's status following the lifecycle state machine.
- Releasing states (`WITHDRAWN`, `CANCELLED`, `MIGRATED`, `REJECTED`) automatically release allocated capacity and recalculate seat occupancy.
- Closed terminal records (`COMPLETED`, `WITHDRAWN`, `CANCELLED`, `MIGRATED`, `REJECTED`) can **ONLY** be reopened via an `AICTE_ADMIN` exceptional workflow requiring a mandatory `exceptional_reason`.

- **Request Body**:
```json
{
  "target_status": "CONFIRMED",
  "reason": "All 3 verification layers passed",
  "exceptional_reason": null
}
```

- **Response `200 OK`**:
```json
{
  "id": "enrollment-uuid",
  "status": "CONFIRMED",
  "verified": true,
  "version": 1,
  "updated_at": "2026-10-23T02:55:00Z"
}
```

- **Response `409 Conflict` (Invalid Transition)**:
```json
{
  "code": "INVALID_TRANSITION",
  "message": "Cannot transition enrollment from 'DRAFT' to 'ACTIVE'.",
  "field": "status",
  "details": {
    "from": "DRAFT",
    "to": "ACTIVE",
    "allowed": ["CANCELLED", "PROVISIONAL"]
  }
}
```

---

## 10. Human Review Cases System

Governs human-in-the-loop exception handling, SLA monitoring, and institutional clarification workflows.

- **Case Types**: `DUPLICATE`, `IDENTITY_MISMATCH`, `SEAT_EXCEPTION`, `APPROVAL_MISMATCH`, `MISSING_IDENTIFIER`, `LATE_SUBMISSION`, `CORRECTION_REQUEST`.
- **Workflow Stages**: `OPEN` $\to$ `ASSIGNED` $\to$ `AWAITING_INSTITUTION` $\to$ `UNDER_DECISION` $\to$ `RESOLVED` | `ESCALATED`.
- **SLA Computation**: `due_at` calculated by severity (`CRITICAL`: 24h, `HIGH`: 48h, `MEDIUM`: 168h, `LOW`: 336h). Exposes `is_overdue` and `hours_remaining`.
- **Decisions**: `DATA_ENTRY_ERROR`, `LEGITIMATE_SEPARATE_ENROLMENT`, `WITHDRAW_ONE_RECORD`, `CONFIRM`, `REJECT`, `ESCALATE` (mandatory reason; consequences applied to enrollments strictly via the state machine).
- **Security Rule**: Institutions can answer clarification requests and attach evidence references (reference + SHA-256 hash, never raw file binaries). **Institutions cannot approve their own exceptions or decide review cases** (HTTP `403 Forbidden`).

### `GET /api/review-cases`
List review cases with institutional scoping, pagination, and SLA overdue filtering.
- **Query Parameters**:
  - `status`: `OPEN` | `ASSIGNED` | `AWAITING_INSTITUTION` | `UNDER_DECISION` | `RESOLVED` | `ESCALATED`
  - `severity`: `CRITICAL` | `HIGH` | `MEDIUM` | `LOW`
  - `case_type`: Case type filter
  - `is_overdue`: `true` | `false`
  - `assigned_to`: Reviewer user UUID
  - `limit`: default 50
  - `offset`: default 0

### `POST /api/review-cases`
Manually opens a review case (AICTE Admin or Reviewer).
- **Request Body**:
```json
{
  "type": "SEAT_EXCEPTION",
  "enrollment_id": "enrollment-uuid",
  "severity": "HIGH",
  "details": {"reason": "Quota category capacity exceeded"}
}
```

### `GET /api/review-cases/{id}`
Retrieves case details, current SLA countdown (`hours_remaining`), and assigned reviewer.

### `POST /api/review-cases/{id}/assign`
Assigns a case to an AICTE Reviewer. Transitions case from `OPEN` to `ASSIGNED`.
- **Request Body**:
```json
{
  "assignee_id": "reviewer-user-uuid"
}
```

### `POST /api/review-cases/{id}/evidence`
Institutions attach evidence references in response to clarification inquiries. Automatically advances case status to `UNDER_DECISION`.
- **Request Body**:
```json
{
  "evidence_ref": "AFFIDAVIT-DOC-2026-088",
  "evidence_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "description": "Notarized affidavit certifying legal surname change"
}
```

### `PATCH /api/review-cases/{id}`
Decides a review case. Strictly prohibited for institutional users (`403 Forbidden`). Applies state machine consequences to the underlying enrollment record.
- **Request Body**:
```json
{
  "decision": "CONFIRM",
  "decision_reason": "Court order and gazette publication validated against registrar records"
}
```

### `GET /api/review-cases/{id}/history`
Fetches the immutable chronological audit log for the review case.

---

## 11. Correction Requests & Immutable Record Versioning

Allows institutions to submit formal correction requests for existing enrollment records.

- **Endpoints**:
  - `POST /api/correction-requests`: Submits a request with reason code, explanation, and proposed changes.
  - `GET /api/correction-requests`: Returns scoped list of correction requests.
  - `GET /api/correction-requests/{id}`: Returns single request with previous state snapshot.
  - `PATCH /api/correction-requests/{id}`: AICTE decision endpoint. Upon approval, increments enrollment version to $N+1$, writes before/after snapshot to `record_versions`, retains the old version permanently, and applies requested updates.
