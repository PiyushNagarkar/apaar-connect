# AICTE Admission Verification Rule Catalogue

> **Notice:** All data is synthetic. Simulated APAAR service (`MOCK_APAAR_V1`).
> Generated automatically from code registry (`services/validation_service.py`).
> Reference Handbook: **AICTE Approval Process Handbook (APH)**

---

## 1. Severity Levels & Workflow Impact

| Severity Level | Description | Behavior |
| :--- | :--- | :--- |
| `INFO` | Advisory notice or telemetry | Stored in audit trail; does not affect lifecycle |
| `WARNING` | Demographic divergence or late submission tag | Flags evidence requirement; allows provisional status |
| `ERROR` | Severe violation or invalid data | **Blocks commit** of the admission row |
| `HIGH` | Authority snapshot or approval issue | Sets status to `UNDER_REVIEW`; opens review case |
| `CRITICAL` | System integrity or data corruption | Halts processing; alerts security auditor |
| `REGULATORY_ALERT` | Quota overflow or unapproved category | Opens AICTE ReviewCase; sets `UNDER_REVIEW` |

*Note: Rule severities can be customized at runtime via the `rule_severity_configs` table.*

---

## 2. Master Rule Registry

| Rule Code | Layer | Name | Default Severity | Description |
| :--- | :--- | :--- | :--- | :--- |
| `RULE_L1_APAAR_MISSING` | **L1 Identity** | APAAR Identifier Missing | `WARNING` &rarr; `ERROR` | Missing APAAR allowed as provisional during grace period (30 days), then escalates to ERROR. |
| `RULE_L1_BAD_FORMAT` | **L1 Identity** | APAAR Format / Luhn Checksum Failure | `ERROR` | Validates that APAAR strictly conforms to 12-digit Luhn mod-10 formula. |
| `RULE_L1_NOT_FOUND` | **L1 Identity** | APAAR Record Not Found | `ERROR` | Valid format but not present in simulated national directory. |
| `RULE_L1_NAME_DOB_MISMATCH` | **L1 Identity** | Name / DOB Demographic Mismatch | `WARNING` | Name or DOB differs from registry record; requests official proof. |
| `RULE_L1_SERVICE_UNAVAILABLE` | **L1 Identity** | Upstream APAAR Service Unavailable | `INFO` / `PENDING` | Simulates gateway timeout; guarantees record remains provisional. |
| `RULE_L2_APPROVAL_MISSING` | **L2 Authority** | Approval Missing for Program/Campus/Shift/Year | `HIGH` | Rejects unapproved programs or branches without AICTE approval. |
| `RULE_L2_SNAPSHOT_MISMATCH` | **L2 Authority** | Approval Snapshot Not Frozen or Superseded | `HIGH` | Admissions must reference an immutable FROZEN AICTE approval. |
| `RULE_L2_LATE_SUBMISSION_WITHOUT_REASON` | **L2 Authority** | Submission After Lock Without Reason Code | `ERROR` | Blocks commits after round lock without an authorized reason code. |
| `RULE_L3_CAPACITY_EXCEEDED` | **L3 Compliance** | Per-Category Approved Capacity Exceeded | `REGULATORY_ALERT` | Occupied seats (CONFIRMED + ACTIVE) exceed approved quota; opens case. |
| `RULE_L3_ZERO_SEATS_APPROVED` | **L3 Compliance** | Admission in Category with Zero Approved Seats | `REGULATORY_ALERT` | Attempted admission in a seat category with 0 approved seats in frozen matrix. |
| `RULE_L3_SUPERNUMERARY_EVIDENCE_MISSING` | **L3 Compliance** | Supernumerary Seat Missing Evidence | `REGULATORY_ALERT` | FN/OCI/Gulf supernumerary seats require valid evidence reference. |
| `RULE_L3_CONTRADICTORY_FLAGS` | **L3 Compliance** | Contradictory Nationality / Domicile Flags | `ERROR` | Prevents contradictory flags (e.g., candidate cannot be both NRI and FN). |
| `RULE_L3_LATE_SUBMISSION` | **L3 Compliance** | Late Admission Submission Tagged | `WARNING` | Tags admissions committed post-deadline under an approved reason code. |

---

## 3. Layer-by-Layer Verification Architecture

### Layer 1: Identity Verification (`MOCK_APAAR_V1`)
1. **Missing APAAR Handling**:
   - `RULE_L1_APAAR_MISSING`: Evaluated through policy engine grace period ($N$ days, default 30).
   - Within grace period: Evaluates as `WARNING` and sets status `PROVISIONAL`.
   - After grace period expires: Escalates to `ERROR` and blocks verification.
2. **Format & Checksum**:
   - `RULE_L1_BAD_FORMAT`: Reverses digits, double-weights odd positions, checks `total % 10 == 0`. Unchecked demographic fields remain `null`.
3. **Fuzzy Demographics**:
   - `RULE_L1_NAME_DOB_MISMATCH`: Normalizes names (whitespace collapsed, titles stripped, token sets matched). If mismatch occurs, evidence is requested.

### Layer 2: Institutional Authority Verification
1. **Approval Existence**:
   - `RULE_L2_APPROVAL_MISSING`: Verifies programme, branch, academic year, campus, and shift against the institution's approved portfolio.
2. **Immutability Enforcement**:
   - `RULE_L2_SNAPSHOT_MISMATCH`: Only `FROZEN` approvals allow student commits. `DRAFT` approvals reject admissions.
3. **Lock & Deadline Controls**:
   - `RULE_L2_LATE_SUBMISSION_WITHOUT_REASON`: Enforces mandatory reason codes (`DATA_ENTRY_ERROR`, `OFFICIAL_CORRECTION`, `TRANSFER_UPDATE`, `WITHDRAWAL_UPDATE`, `APPROVAL_UPDATE`, `OTHER_REQUIRES_EXPLANATION`) once round is locked.

### Layer 3: Seat Compliance & Category Quotas
1. **Capacity Isolation Principle**:
   - `RULE_L3_CAPACITY_EXCEEDED`: Computes occupancy counting **only CONFIRMED + ACTIVE** students.
   - **Spare supernumerary seats must NOT absorb regular students!** If regular quota is 120 and 121 are admitted, it triggers `REGULATORY_ALERT` even if 15 supernumerary seats are empty.
2. **Withdrawn Seats**:
   - Students with status `WITHDRAWN`, `CANCELLED`, or `REJECTED` are excluded from occupied counts, immediately freeing capacity for subsequent admissions.
3. **Contradictory Flags**:
   - `RULE_L3_CONTRADICTORY_FLAGS`:
     - `nri_flag` and `fn_flag` cannot both be true.
     - `seat_type == "NRI"` requires `nri_flag == True`.
     - `seat_type == "SUPERNUMERARY_FN_OCI_PIO"` requires `fn_flag == True` or `oci_flag == True`.
     - `seat_type == "REGULAR"` rejects `fn_flag == True`.

---

## 4. Multi-Layer Verdict Logic

An enrollment is marked `verified = true` **if and only if** all three independent verification layers pass:

$$\text{verified} \iff (\text{L1 Identity} = \text{PASSED}) \land (\text{L2 Authority} = \text{PASSED}) \land (\text{L3 Compliance} = \text{PASSED})$$

- Any `ERROR` severity blocks commit.
- Any `REGULATORY_ALERT` or `HIGH` severity generates an AICTE `ReviewCase` and assigns `status = "UNDER_REVIEW"`.
