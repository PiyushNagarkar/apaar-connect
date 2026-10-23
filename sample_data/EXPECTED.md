# AICTE APAAR Connect: Expected Validation & Anomaly Verification Matrix

This document lists the exact expected behavior, rule triggers, and alert classifications
for every row in `imperfect_demo.csv`. Automated test suites, integration benchmarks, and
live evaluators assert against these specifications.

## Summary of Test Cases Planted (Total Rows: 40)

- **Rows 1-10**: Programme A Compliant Normal / Quotas (REGULAR, NRI, FN, OCI, Gulf Worker, TFW).
- **Rows 11-12**: Twin Pair Exception (same DOB, same phone, same surname, distinct first names) $\implies$ **MUST NOT ALERT**.
- **Rows 13-14**: Progression Exception (completed undergraduate degree progressing to post-grad) $\implies$ **NO ALERT**.
- **Rows 15-19**: Identity Verification Cases (`PASSED`, `FAILED(format)`, `FAILED(mismatch)`, `NOT_PROVIDED`, `UNAVAILABLE`).
- **Rows 20-24**: Duplicate Cases (Same-institution, Cross-institution, Fuzzy typo pair).
- **Rows 25-28**: Cross-Field Consistency (Contradictory NRI/FN flags, Seat vs Flag mismatch, FN in regular seat).
- **Rows 29-33**: Programme B Seat Over-Admission (REGULAR capacity exceeded while supernumerary unused).
- **Rows 34-36**: Programme C Unapproved Seat Allocation (Zero approved seats for NRI / Supernumerary).
- **Rows 37-40**: Data Quality & Hygiene (Missing name, invalid DOB format, missing admission date, unapproved branch).

---

## Complete Row-by-Row Assertion Table

| Row # | Student Name | APAAR ID | Seat Type | Expected Outcome | Rule / Code | Alert Level | Reason & Explanation |
| :---: | :--- | :--- | :--- | :---: | :--- | :---: | :--- |
| 1 | Priya Patel | `987654321015` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid student enrollment, REGULAR seat, OPEN category. |
| 2 | Rahul Sharma | `987654321013` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid student enrollment, REGULAR seat, OBC_NCL category. |
| 3 | Aarav Sharma | `123456789012` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid student enrollment, REGULAR seat, SC category. |
| 4 | Vikram Singh | `111122223333` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid student enrollment, REGULAR seat, ST category. |
| 5 | Priya Patel | `987654321012` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid student enrollment, REGULAR seat, EWS category. |
| 6 | Deepak Verma | `880000001007` | `NRI` | **COMMITTED** | `VALID` | `NONE` | Valid NRI seat admission with nri_flag=true. |
| 7 | Fatima Mansoor | `880000001015` | `SUPERNUMERARY_FN_OCI_PIO` | **COMMITTED** | `VALID` | `NONE` | Valid Supernumerary Foreign National admission with fn_flag=true. |
| 8 | Neil Mukherjee | `880000001023` | `SUPERNUMERARY_FN_OCI_PIO` | **COMMITTED** | `VALID` | `NONE` | Valid Supernumerary OCI admission with oci_flag=true. |
| 9 | Tariq Aziz | `880000001031` | `SUPERNUMERARY_GULF_WORKER_CHILD` | **COMMITTED** | `VALID` | `NONE` | Valid Supernumerary Children of Indian Workers in Gulf Countries admission. |
| 10 | Sneha Kulkarni | `880000001049` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Valid REGULAR seat admission under Tuition Fee Waiver (TFW) scheme. |
| 11 | Rohan Verma | `880000001056` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Twin brother: shares DOB & parent mobile with Kavya Verma, but different first name and distinct APAAR. Must NOT alert. |
| 12 | Kavya Verma | `880000001064` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Twin sister: shares DOB & parent mobile with Rohan Verma, but different first name and distinct APAAR. Must NOT alert. |
| 13 | Arjun Nair | `880000001072` | `REGULAR` | **HISTORICAL** | `VALID` | `NONE` | Student completed B.Tech in 2024 (status COMPLETED in DB). |
| 14 | Arjun Nair | `880000001072` | `REGULAR` | **COMMITTED** | `TIER_PROGRESSION` | `NONE` | Post-graduate admission following completed undergraduate degree. Normal progression: no duplicate case created. |
| 15 | Isha Chatterjee | `880000001080` | `REGULAR` | **COMMITTED** | `PASSED` | `NONE` | Identity verification PASSED: valid APAAR format + Luhn checksum + exact match in registry. |
| 16 | Manish Gupta | `880000001089` | `REGULAR` | **FAILED** | `INVALID_APAAR_FORMAT` | `HIGH` | Identity verification FAILED(format): 12-digit APAAR fails Luhn mod-10 check digit. |
| 17 | Priya Patel | `987654321015` | `REGULAR` | **FAILED** | `IDENTITY_DEMOGRAPHIC_MISMATCH` | `HIGH` | Identity verification FAILED(mismatch): APAAR exists in registry but DOB 1998-01-01 does not match official record (2005-03-21). |
| 18 | Siddharth Rao | `*(Not Provided)*` | `REGULAR` | **COMMITTED_PROVISIONAL** | `NOT_PROVIDED` | `LOW` | APAAR not provided at time of admission; allowed within grace period as PROVISIONAL. |
| 19 | Aniket Deshmukh | `000000111222` | `REGULAR` | **PENDING** | `UNAVAILABLE` | `LOW` | Upstream national APAAR gateway timeout (504). Held in PENDING for retry. |
| 20 | Amit Jadhav | `880000001098` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | First legitimate enrollment of Amit Jadhav at IIT Delhi. |
| 21 | Amit Jadhav | `880000001098` | `REGULAR` | **FAILED_OR_REVIEW** | `DUPLICATE_SAME_INSTITUTION` | `HIGH` | Duplicate APAAR submitted twice within the same institution (Tier 2 High duplicate alert). |
| 22 | Ananya Iyer | `987654321014` | `REGULAR` | **FAILED_OR_REVIEW** | `DUPLICATE_CROSS_INSTITUTION` | `CRITICAL` | Cross-institution duplicate: Student actively enrolled at NIT Trichy attempted at IIT Delhi (Tier 1 Critical). |
| 23 | Rajesh Kumar Sharma | `880000001106` | `REGULAR` | **COMMITTED** | `VALID` | `NONE` | Primary record for Rajesh Kumar Sharma. |
| 24 | Rajeysh Kumar Sharma | `880000001114` | `REGULAR` | **REVIEW_FLAGGED** | `TIER_FUZZY` | `MEDIUM` | Fuzzy typo duplicate match: Rajeysh vs Rajesh (Jaro-Winkler >= 0.92) with identical DOB. |
| 25 | Karan Malhotra | `880000001122` | `NRI` | **FAILED** | `CONTRADICTORY_FLAGS` | `HIGH` | Contradictory citizenship flags: Student cannot be both an NRI (Indian citizen) and FN (foreign national). |
| 26 | Diya Sen | `880000001130` | `NRI` | **FAILED** | `NRI_SEAT_FLAG_MISMATCH` | `HIGH` | Admitted under NRI seat quota but nri_flag is false. |
| 27 | Reyansh Bose | `880000001148` | `SUPERNUMERARY_FN_OCI_PIO` | **FAILED** | `SUPERNUMERARY_FLAG_MISMATCH` | `HIGH` | Admitted under SUPERNUMERARY_FN_OCI_PIO but neither fn_flag nor oci_flag is true. |
| 28 | Hans Mueller | `880000001155` | `REGULAR` | **FAILED** | `FN_IN_REGULAR_SEAT` | `CRITICAL` | Foreign National candidate allocated under REGULAR approved intake instead of supernumerary quota. |
| 29 | Student OverFlow1 IT | `880000001156` | `REGULAR` | **FAILED_OR_ALERT** | `CAPACITY_EXCEEDED` | `CRITICAL` | Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused. |
| 30 | Student OverFlow2 IT | `880000001157` | `REGULAR` | **FAILED_OR_ALERT** | `CAPACITY_EXCEEDED` | `CRITICAL` | Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused. |
| 31 | Student OverFlow3 IT | `880000001158` | `REGULAR` | **FAILED_OR_ALERT** | `CAPACITY_EXCEEDED` | `CRITICAL` | Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused. |
| 32 | Student OverFlow4 IT | `880000001159` | `REGULAR` | **FAILED_OR_ALERT** | `CAPACITY_EXCEEDED` | `CRITICAL` | Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused. |
| 33 | Student OverFlow5 IT | `880000001160` | `REGULAR` | **FAILED_OR_ALERT** | `CAPACITY_EXCEEDED` | `CRITICAL` | Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused. |
| 34 | Aditya Reddy | `880000001163` | `NRI` | **FAILED** | `ZERO_APPROVED_SEATS` | `CRITICAL` | Admission under NRI category in Mechanical Engineering where 0 NRI seats are approved by AICTE. |
| 35 | Sarah Connor | `880000001171` | `SUPERNUMERARY_FN_OCI_PIO` | **FAILED** | `ZERO_APPROVED_SEATS` | `CRITICAL` | Admission under SUPERNUMERARY_FN_OCI_PIO in Mechanical Engineering where 0 supernumerary seats are approved. |
| 36 | Farhan Qureshi | `880000001189` | `SUPERNUMERARY_GULF_WORKER_CHILD` | **FAILED** | `ZERO_APPROVED_SEATS` | `CRITICAL` | Admission under SUPERNUMERARY_GULF_WORKER_CHILD in Mechanical Engineering where 0 seats are approved. |
| 37 | *(Blank Name)* | `880000001197` | `REGULAR` | **FAILED** | `MISSING_NAME` | `HIGH` | Required demographic validation failure: Student legal name is empty. |
| 38 | Tanvi Rao | `880000001205` | `REGULAR` | **FAILED** | `INVALID_DOB` | `HIGH` | Date of birth format invalid (cannot be parsed into ISO YYYY-MM-DD). |
| 39 | Pranav Kulkarni | `880000001213` | `REGULAR` | **FAILED** | `MISSING_ADMISSION_DATE` | `HIGH` | Mandatory admission date is missing. |
| 40 | Meera Joshi | `880000001221` | `REGULAR` | **FAILED** | `UNAPPROVED_PROGRAMME_BRANCH` | `CRITICAL` | Institutional authority failure: No AICTE Extension of Approval (EoA) exists for ASTRONAUTICAL_ENGINEERING. |

---

## Evaluation & Live Demo Instructions

1. **Dry-Run Validation Test**:
   ```bash
   # Upload and perform a dry run
   POST /api/submissions/upload (multipart: imperfect_demo.csv)
   POST /api/submissions/{id}/validate-dry-run
   ```
   *Expected Result*: Returns summary with 14 Valid rows, 26 Invalid rows, matching exactly the planted codes above.

2. **Risk & Anomaly Priority Verification**:
   ```bash
   GET /api/analytics/institution/{institution_id}/anomalies
   ```
   *Expected Result*: Programme B flags `SEAT_CAPACITY_EXCEEDED` alert; Programme C flags `NO_APPROVAL_CATEGORY` alert;
   Duplicate queue highlights Row 21 (`DUPLICATE_SAME_INSTITUTION`) and Row 22 (`DUPLICATE_CROSS_INSTITUTION`).

3. **Zero-False-Positive Assurances**:
   - **Rows 11 & 12 (Twins)** produce zero duplicate cases.
   - **Rows 13 & 14 (Progression)** produce zero duplicate cases (`TIER_PROGRESSION` flagged without review case).
