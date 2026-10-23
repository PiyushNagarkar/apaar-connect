# AICTE APAAR Connect — Demonstration Walkthrough & Script

> **REGULATORY SANDBOX NOTICE**  
> **Scale:** Demo-Scale Environment. All student identities, APAAR numbers, and institution records are synthetically generated. Identity verification is simulated using adapter `MOCK_APAAR_V1`. Never represent these benchmark results or demonstration metrics as national-scale.

---

## Overview

This document provides an end-to-end presentation script for live evaluators and regulatory stakeholders. It comprises:
1. **The 4-Moment Live Walkthrough (4 to 5 Minutes)**: Demonstrates the statutory core from batch ingestion to instant cryptographic revocation.
2. **The 30-Second Failure Suite**: Demonstrates graceful resilience against upstream gateway timeouts, cross-institution tampering, and expired student credentials.

---

## Pre-Demo Checklist

Run the following commands to initialize a pristine, deterministic state:

```bash
# 1. Reset and populate database (seed: 42)
make demo-reset

# 2. Verify system health and all 7 role logins
make demo-check
```

### Credentials Cheat Sheet (Password: `DemoPass@123`)

| Role | Username | Demonstrates |
| :--- | :--- | :--- |
| **National Regulator** | `admin@aicte.gov.in` | National capacity dashboard, EoA approvals, systemic risk |
| **State / Regulatory Reviewer**| `reviewer@aicte.gov.in` | Human adjudication queue, anomaly scoring, exception overrides |
| **Institution Administrator** | `admin@iitd.ac.in` | Institutional capacity, quota ceilings, program freeze orders |
| **Institution Operator** | `operator@iitd.ac.in` | CSV bulk upload, dry-run previews, single admission entry |
| **Student** | `student@demo.aicte.gov.in` | Student card, DigiLocker consent history, verifiable QR |
| **Auditor** | `auditor@aicte.gov.in` | Append-only tamper-evident audit logs, SHA-256 chain verification |
| **Public Verifier (Employer)** | `verifier@tcs.com` | Zero-knowledge public credential scanner, Ed25519 badges |

---

## Part 1: The 4-Moment Live Walkthrough

### Moment 1: Batch Upload with Dry-Run Purity (`sample_data/imperfect_demo.csv`)

- **Persona:** Institution Operator (`operator@iitd.ac.in`)
- **Portal URL:** `http://localhost:5173/institution` or `http://localhost:8000/docs`
- **Objective:** Prove that dry-run validation parses imperfect dirty data, flags statutory violations, and **writes zero records to enrollments** without reserving seats.

#### Walkthrough Steps:
1. Navigate to the **Institution Portal** → **Admissions Upload** tab.
2. Drag and drop `sample_data/imperfect_demo.csv`.
3. Click **"Run Dry-Run Validation"** (or call `POST /api/submissions/{id}/validate`).
4. **Key Talking Points:**
   - *"Notice how the engine immediately sanitizes spreadsheet formula injection characters (`=`, `+`, `-`, `@`) and cleans leading UTF-8 BOM bytes."*
   - *"The dry-run completes in milliseconds, classifying 5 rows as invalid."*
   - *"Check the database enrollment count immediately after dry-run: **exactly 0 seats have been reserved**, and **0 records have been written to enrollments**. The statutory ceiling is protected."*

---

### Moment 2: Category Quota Isolation & Duplicate APAAR Detection

- **Persona:** Institution Operator & Reviewer
- **Objective:** Prove that supernumerary seats never absorb regular seats (Rule 3) and duplicate APAAR records trigger deterministic alerts (Rule 5).

#### Walkthrough Steps:
1. In the Validation Results table, examine the flagged error rows:
   - **Row 14 (Category Spillover Violation):** Candidate submitted under `REGULAR` quota when regular seats are exhausted, even though `SUPERNUMERARY_FN_OCI_PIO` seats remain available.
     - *Explanation Shown:* `"Approved capacity for REGULAR seats is exhausted. Supernumerary seats are strictly isolated and cannot absorb regular candidates."*
   - **Row 19 (Cross-Institution Duplicate):** Same APAAR ID already enrolled in another institution for academic year 2024-2025.
     - *Explanation Shown:* `"Candidate has an active confirmed enrollment at another approved institution."* (Tier 1 Critical duplicate).
   - **Row 21 (Zero Approved Quota):** Candidate admitted under a quota category with 0 seats in the AICTE Approval Order (EoA).
2. **Key Talking Points:**
   - *"AICTE rules prohibit quota fungibility. Extra seats in Gulf Worker or FN quotas cannot be secretly reallocated to regular students."*
   - *"The duplicate detection engine calculates a keyed blind SHA-256 index, detecting multi-institution ghost admissions across India without decrypting or exposing the underlying identity."*

---

### Moment 3: Adjudicate Review Case & Live Dashboard State Transition

- **Persona:** AICTE Reviewer (`reviewer@aicte.gov.in`)
- **Portal URL:** `http://localhost:5173/reviews` & `http://localhost:5173/command-centre`
- **Objective:** Adjudicate an ambiguous admission case, observe explainable scoring, and watch the National Dashboard update in real time with an immutable audit trail.

#### Walkthrough Steps:
1. Navigate to the **Review Queue** (`/reviews`).
2. Open case `REV-DEMO-01` (Demographic discrepancy: Name typo *"Priya P"* vs *"Priya Patel"* in APAAR directory).
3. Inspect the **Explainable Risk-Priority Score**:
   - Identity Match Score: `82%` (Phonetic Soundex & Levenshtein match)
   - Discrepancy Level: `MEDIUM`
   - Suggested Action: `FLAG_FOR_INSTITUTION_CLARIFICATION`
4. Click **"Approve with Regulatory Note"**:
   - Select reason: `OFFICIAL_CORRECTION`
   - Enter note: `"Aadhaar update receipt verified by State Directorate."`
   - Click **Submit Resolution**.
5. Switch to **National Dashboard** (`/command-centre`):
   - Notice the **Open Review Cases** count decrements immediately.
   - Notice the **Verified Enrollments** counter increments.
6. Switch to **Audit Trail** (`/audit`):
   - Observe the new event: `REVIEW_RESOLVE` with actor `reviewer@aicte.gov.in`, SHA-256 hash chaining, and timestamp in UTC.

---

### Moment 4: Verifiable Credential Issuance & Instant 0-ms Revocation

- **Persona:** Institution Admin (`admin@iitd.ac.in`) & Public Verifier (`verifier@tcs.com`)
- **Portal URL:** `http://localhost:5173/verify`
- **Objective:** Demonstrate cryptographic student credential issuance with an Ed25519 signature, public zero-knowledge verification, and instant server-side revocation.

#### Walkthrough Steps:
1. **Issue Credential:**
   - As Institution Admin, go to Confirmed Student Card (`/student-card`) and click **"Generate Verifiable Credential"**.
   - An Ed25519 signed JSON credential with public QR code is issued.
2. **Public Verification:**
   - Navigate to the Public Verifier portal (`/verify`).
   - Paste the public reference: `VALID-REF-101` (or click Preset **Valid Ref**).
   - Click **Verify**.
   - **Result:** Emerald green badge: **"VALID CREDENTIAL"** with `"Cryptographic Ed25519 signature verified. Enrolment in good statutory standing."`
   - *Notice:* Zero sensitive personal data (no date of birth, no Aadhaar number, no contact info) is disclosed to the verifier (DPDP Act Data Minimization).
3. **Instant Revocation:**
   - As Regulator, execute revocation: `POST /api/credentials/CRED-01/revoke` with reason `"Court order regarding canceled admission round"`.
   - Refresh or re-verify `VALID-REF-101` on the Public Verifier (`/verify`).
   - **Result:** Badge immediately changes to rose red: **"REVOKED CREDENTIAL"** displaying revocation timestamp and statutory revocation justification.
   - **Talking Point:** *"Revocation is immediate. Because our registry maintains an authoritative cryptographic revocation list, there is zero cache staleness or propagation delay."*

---

## Part 2: The 30-Second Failure & Resilience Demo

Showcase system stability when real-world failures strike:

### 1. Identity Gateway Outage (`UNAVAILABLE`) — 10 Seconds
- **Trigger:** Request verification for a candidate where simulated gateway returns a timeout.
- **Observed Behavior:**
  - Status shows slate gray badge: **`SERVICE UNAVAILABLE`**.
  - **Crucial Invariant (Contract 6):** The candidate is **NEVER** marked as `FAILED` (which would wrongfully reject a valid student) and **NEVER** marked as `VERIFIED` (which would allow fraudulent unverified entry).
  - The record is placed in a non-punitive 30-day statutory grace period with scheduled automatic retry.

### 2. Multi-Tenant Scope Violation Blocked (`403 FORBIDDEN`) — 10 Seconds
- **Trigger:** Log in as Operator of Institution A (IIT Delhi) and attempt to inspect Institution B (COEP Tech) admissions via `GET /api/institutions/1-1003/admissions`.
- **Observed Behavior:**
  - The server immediately rejects the request with HTTP **403 Forbidden** (`code: FORBIDDEN`).
  - Error message: `"Scope violation: User belongs to institution '1-1001' and cannot access institution '1-1003'."`
  - Zero rows from Institution B leak to Institution A.

### 3. Expired Horizon Credential — 10 Seconds
- **Trigger:** Navigate to `/verify/EXPIRED-REF-303` (or click Preset **Expired Ref**).
- **Observed Behavior:**
  - Amber badge: **`EXPIRED CREDENTIAL`**.
  - Subtitle: `"This verifiable credential has passed its validity horizon and requires renewal."`
  - Verifier is prevented from accepting an outdated degree completion claim.

---

## Demonstration Script Summary Card

```
+-----------------------------------------------------------------------------------+
| AICTE APAAR CONNECT LIVE DEMO SCRIPT CHEAT SHEET                                 |
+-----------------------------------------------------------------------------------+
| 1. Upload imperfect_demo.csv  -> 5 dirty rows caught, 0 seats taken (Dry-Run Pure)|
| 2. Quota & Duplicate Engine   -> Isolated quotas protected, duplicate APAARs found|
| 3. Adjudicate & Dashboard     -> 1-click review, explainable score, live metrics  |
| 4. Issue & Revoke Credential  -> Ed25519 signature, public QR, 0-ms revocation    |
| + 30s Resilience Demo         -> UNAVAILABLE safety, 403 boundary, EXPIRED badge  |
+-----------------------------------------------------------------------------------+
```
