# APAAR Connect - Authentication & Authorization (RBAC) Specification

> **NOTICE:** All data is synthetic. Simulated APAAR service (`MOCK_APAAR_V1`).

---

## 1. Authentication Architecture

### 1.1 Password Hashing
- **Algorithm**: `bcrypt` (with automatic 72-byte safe truncation and unique salt generation per credential).
- Implemented in `backend/security/crypto.py`.

### 1.2 JWT Access Tokens (Short-Lived)
- **Token Delivery Choice**: **Authorization Header (`Bearer <token>`) with companion HttpOnly Cookie (`access_token`)**.
- **Rationale**:
  - **Authorization Header**: Ideal for REST API consumers, CLI scripts, and decoupled frontend clients.
  - **HttpOnly Cookie**: Prevents Cross-Site Scripting (XSS) attacks in modern web browsers by ensuring JavaScript execution environments cannot access the token directly.
  - Both methods are checked seamlessly by the `get_current_user` dependency.
- **Expiry**: Short-lived, **15 minutes** (`expires_in: 900` seconds).
- **Payload Claims**:
  ```json
  {
    "sub": "user-uuid-123",
    "email": "operator.iitd@iitd.ac.in",
    "role": "INSTITUTION_OPERATOR",
    "institution_id": "inst-iitd-uuid",
    "exp": 1729650000,
    "iat": 1729649100
  }
  ```

---

## 2. Authentication Endpoints

| Endpoint | Method | Description | Security |
|---|---|---|---|
| `/api/auth/login` | `POST` | Authenticates email & password, enforces rate limiting, logs audit events, sets HttpOnly cookie, returns JWT | Public + Rate-limited |
| `/api/auth/logout` | `POST` | Clears HttpOnly cookie session and logs audit event | Session / Bearer |
| `/api/auth/me` | `GET` | Returns current user profile, role, institution scope, and permission list | `require_authenticated_user` |

---

## 3. Reusable Security Dependencies

### 3.1 `require_roles(*allowed_roles)`
Enforces that the caller's role matches one of the specified allowed roles.
- Returns HTTP `403 Forbidden` if unauthorized.
```python
@router.post("/approvals/freeze")
def freeze_approval(user = Depends(require_roles(ROLE_AICTE_ADMIN))):
    ...
```

### 3.2 `institution_scope(user)` (Rule 7)
Guarantees institutional data isolation across all tenant boundaries:
- **Never trusts `institution_id` from the request body or URL** for institution users.
- For `INSTITUTION_ADMIN` and `INSTITUTION_OPERATOR`, all operations and queries are automatically locked to `user.institution_id`.
- If an operator from Institution A requests or accesses an enrollment belonging to Institution B, `institution_scope` raises HTTP `403 Forbidden`.
```python
@router.get("/enrollments/{enrollment_id}")
def get_enrollment(enrollment_id: str, scope: InstitutionScope = Depends(institution_scope)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    scope.validate_access(enrollment.institution_id) # Raises 403 on cross-institution access
```

---

## 4. Field-Level Privacy Masking Helper (Rule 10)

Implemented in `backend/security/masking.py`:
- **Raw APAAR Ciphertext**: **NEVER exposed to any role** (stored encrypted with AES-256-GCM).
- **STUDENT**: When viewing own record, sees `name`, `apaar_masked` (`XXXX-XXXX-1234`), `dob`, `gender`, `mobile_last4`. If attempting to view another student's record, returns HTTP `403 Forbidden`.
- **INSTITUTION_***: Sees student demographic details and `apaar_masked`.
- **AICTE_REVIEWER**: Sees student details, `apaar_masked`, and `apaar_hash` for duplicate adjudication.
- **AUDITOR**: Receives pseudonymized name (`A**** S****`), masked DOB (`2005-XX-XX`), `apaar_masked`, and `apaar_hash` for cryptographic proof of uniqueness without revealing student identity.

---

## 5. Rate Limiting & Failed Login Auditing

- **Sliding Window Rate Limiter**: Maximum 5 attempts per 60 seconds per IP/email.
- Exceeding limit raises HTTP `429 Too Many Requests`.
- Failed logins write an immutable `AuditEvent` (`action="AUTH_LOGIN_FAILED"`) with caller IP, timestamp, and request ID.

---

## 6. Seeded 7 Demo Users

| # | Role | Email | Institution | Password | Purpose |
|---|---|---|---|---|---|
| 1 | `AICTE_ADMIN` | `admin@aicte.gov.in` | Global (None) | `Password123!` | Approvals, seat matrix freezing, credential revocation |
| 2 | `AICTE_REVIEWER` | `reviewer@aicte.gov.in` | Global (None) | `Password123!` | Adjudicating duplicate candidates & seat overflow cases |
| 3 | `INSTITUTION_ADMIN` | `admin.iitd@iitd.ac.in` | IIT Delhi | `Password123!` | Managing institution admissions, credentials & operators |
| 4 | `INSTITUTION_OPERATOR` | `operator.iitd@iitd.ac.in` | IIT Delhi | `Password123!` | Uploading student batches for IIT Delhi |
| 5 | `INSTITUTION_OPERATOR` | `operator.nitt@nitt.edu` | NIT Trichy | `Password123!` | Uploading student batches for NIT Trichy |
| 6 | `STUDENT` | `student.priya@student.gov.in` | IIT Delhi | `Password123!` | Viewing own admission status & verified QR credential |
| 7 | `AUDITOR` | `auditor@cag.gov.in` | Global (None) | `Password123!` | Independent compliance inspection (Read-only) |

---

## 7. Role-Based Access Control (RBAC) Matrix

| Feature / Action | `AICTE_ADMIN` | `AICTE_REVIEWER` | `INSTITUTION_ADMIN` | `INSTITUTION_OPERATOR` | `STUDENT` | `AUDITOR` | `VERIFIER` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Create / Freeze Program Approvals** | **Allowed** | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| **Edit Seat Quotas / Allocations** | **Allowed** | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| **View Approvals & Seat Matrix** | **Allowed** | **Allowed** | **Allowed** (Own) | **Allowed** (Own) | Denied (403) | **Allowed** (Read) | Denied (403) |
| **Submit Admission Records** | **Allowed** | Denied (403) | **Allowed** (Own) | **Allowed** (Own) | Denied (403) | Denied (403) | Denied (403) |
| **View Enrollments** | **Allowed** (All) | **Allowed** (All) | **Allowed** (Own Inst) | **Allowed** (Own Inst) | Denied (403) | **Allowed** (All Read) | Denied (403) |
| **Adjudicate / Decide Review Cases** | **Allowed** | **Allowed** | Denied (403) | Denied (403) | Denied (403) | Denied (403) | Denied (403) |
| **View Review Cases** | **Allowed** | **Allowed** | **Allowed** (Own Inst) | Denied (403) | Denied (403) | **Allowed** (Read) | Denied (403) |
| **Read Student Record (Self)** | **Allowed** | **Allowed** | **Allowed** (Own Inst) | **Allowed** (Own Inst) | **Allowed** (Own Record) | **Allowed** (Masked) | Denied (403) |
| **Read Student Record (Cross/Other)** | **Allowed** | **Allowed** | Denied (403) | Denied (403) | **Denied (403)** | **Allowed** (Masked) | Denied (403) |
| **Write / Mutate Any Data** | **Allowed** | Denied (403) | **Allowed** (Own Inst) | **Allowed** (Own Inst) | Denied (403) | **Denied (403)** | Denied (403) |
| **View Tamper-Evident Audit Logs** | **Allowed** | Denied (403) | Denied (403) | Denied (403) | Denied (403) | **Allowed** (Read) | Denied (403) |
| **Verify QR Credential (Public)** | **Allowed** | **Allowed** | **Allowed** | **Allowed** | **Allowed** | **Allowed** | **Allowed** |
