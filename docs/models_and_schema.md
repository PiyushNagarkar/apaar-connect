# Database Schema and Model Dictionary

All 15 models feature:
- **UUID Primary Keys** (String 36 UUIDv4)
- **Timezone-aware Timestamps**: `created_at` (UTC) and `updated_at` (UTC)

---

## Model Specifications

| # | Model / Table Name | Key Attributes | Indexes & Constraints |
|---|--------------------|----------------|------------------------|
| 1 | `institutions` | `code`, `name`, `status` | Unique index on `code` |
| 2 | `users` | `email`, `password_hash`, `role`, `institution_id` (nullable FK), `is_active` | Unique index on `email`, index on `institution_id` |
| 3 | `program_approvals` | `institution_id`, `programme`, `branch`, `campus`, `shift`, `academic_year`, `approval_ref`, `version`, `status` [DRAFT, FROZEN], `frozen_at`, `frozen_by`, `supersedes_id` | Indexes on `academic_year`, `approval_ref`, `status`, FK to `institutions.id` |
| 4 | `seat_allocations` | `approval_id`, `seat_type` [REGULAR, NRI, SUPERNUMERARY_FN_OCI_PIO, SUPERNUMERARY_GULF_WORKER_CHILD, OTHER], `approved_count`, `rule_version` | Unique constraint on `(approval_id, seat_type)` |
| 5 | `students` | `apaar_encrypted`, `apaar_hash`, `apaar_masked`, `name`, `name_normalized`, `dob`, `gender`, `mobile_hash`, `mobile_last4`, `email_hash`, `consent_status` | **Index on `apaar_hash`** (Blind index lookup) |
| 6 | `enrollments` | `student_id`, `institution_id`, `approval_id`, `academic_year`, `seat_type`, `category`, `admission_date`, `round`, `status`, `identity_status`, `authority_status`, `compliance_status`, `verified` (bool), `version` | **Composite index on `(institution_id, academic_year)`**, **Composite index on `(approval_id, seat_type, status)`** |
| 7 | `submissions` | `institution_id`, `uploaded_by`, `round`, `status`, `idempotency_key`, `counts` (JSON) | Index on `idempotency_key`, FK to `institutions.id`, `users.id` |
| 8 | `submission_rows` | `submission_id`, `row_number`, `raw` (JSON), `normalized` (JSON), `outcome` [VALID, INVALID, COMMITTED, FAILED, UNPROCESSED], `errors` (JSON), `row_key` | **DB Unique on `(submission_id, row_number)`**, **DB Unique on `row_key`** |
| 9 | `identity_checks` | `student_id`, `request_id`, `source` (default `MOCK_APAAR_V1`), `status`, `exists`, `name_match`, `dob_match`, `raw` (JSON) | Indexes on `student_id`, `request_id` |
| 10 | `validation_issues` | `enrollment_id` (nullable FK), `row_id` (nullable FK), `rule_code`, `severity`, `message`, `status` | Indexes on `enrollment_id`, `row_id`, `rule_code` |
| 11 | `duplicate_candidates` | `enrollment_a`, `enrollment_b`, `match_type`, `score`, `reasons` (JSON), `status` | Indexes on `enrollment_a`, `enrollment_b` |
| 12 | `review_cases` | `type`, `severity`, `priority`, `enrollment_id`, `assigned_to` (nullable FK), `status`, `decision`, `decision_reason`, `evidence` (JSON), `due_at` | Indexes on `priority`, `status`, `enrollment_id`, `assigned_to` |
| 13 | `consent_records` | `student_id`, `purpose`, `status`, `reference`, `timestamp` | Index on `student_id` |
| 14 | `record_versions` | `entity_type`, `entity_id`, `version`, `snapshot` (JSON), `change_reason`, `actor_id` | Indexes on `entity_type`, `entity_id` |
| 15 | `credentials` | `enrollment_id`, `public_ref`, `payload` (JSON), `signature`, `key_id`, `expires_at`, `revoked_at`, `revoke_reason`, `status` | **DB Unique on `public_ref`**, unique on `enrollment_id` |
| 16 | `audit_events` | `actor_id`, `action`, `entity_type`, `entity_id`, `reason`, `request_id`, `prev_hash` (nullable), `hash` (nullable) | Indexes on `action`, `entity_type`, `entity_id`, `request_id` |

---

## Database Enforcements

1. **Submission Row Uniqueness**:
   ```sql
   CONSTRAINT uq_submission_row_number UNIQUE (submission_id, row_number)
   CONSTRAINT uq_submission_row_key UNIQUE (row_key)
   ```
2. **Credential Public Reference Uniqueness**:
   ```sql
   CONSTRAINT uq_credentials_public_ref UNIQUE (public_ref)
   ```
3. **Seat Matrix Allocation Uniqueness**:
   ```sql
   CONSTRAINT uq_approval_seat_type UNIQUE (approval_id, seat_type)
   ```
