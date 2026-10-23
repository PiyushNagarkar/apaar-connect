export type SystemRole =
  | 'AICTE_ADMIN'
  | 'AICTE_REVIEWER'
  | 'INSTITUTION_ADMIN'
  | 'INSTITUTION_OPERATOR'
  | 'STUDENT'
  | 'VERIFIER'
  | 'AUDITOR';

export interface UserContext {
  role: SystemRole;
  userId: string;
  institutionId?: string;
  studentId?: string;
  name: string;
}

export interface Institution {
  id: string;
  aicte_permanent_id: string;
  name: string;
  state: string;
  district?: string;
  institution_type: string;
  status: string;
  is_autonomous: boolean;
  created_at: string;
  updated_at: string;
}

export interface AcademicProgram {
  id: string;
  institution_id: string;
  program_code: string;
  name: string;
  degree_level: string;
  shift: string;
  is_active: boolean;
}

export interface SeatCategoryCapacity {
  id: string;
  snapshot_id: string;
  program_id: string;
  category: string;
  quota_type: 'REGULAR' | 'SUPERNUMERARY';
  approved_intake: number;
  rule_version: string;
}

export interface ApprovalSnapshot {
  id: string;
  institution_id: string;
  academic_year: string;
  order_number: string;
  approval_date: string;
  valid_from: string;
  valid_to: string;
  rule_version: string;
  is_frozen: boolean;
  snapshot_hash: string;
  approved_by_officer: string;
  created_at: string;
}

export interface VerificationSummary {
  l1: {
    adapter_version: string;
    is_simulated: boolean;
    status: 'PASS' | 'FAIL' | 'UNAVAILABLE';
    confidence_score: number;
    matched_fields: string[];
    mismatched_fields: string[];
    reason_code?: string;
    reason_message: string;
    synthetic_notice: string;
  };
  l2: {
    status: 'PASS' | 'FAIL' | 'SKIPPED_DUE_TO_L1_UNAVAILABLE';
    snapshot_id?: string;
    order_number?: string;
    reason_code?: string;
    reason_message?: string;
    quota_type?: string;
    approved_intake?: number;
  };
  l3: {
    status?: 'PASS' | 'FAIL' | 'SKIPPED_DUE_TO_L1_UNAVAILABLE';
    is_duplicate?: boolean;
    is_cross_institution_duplicate?: boolean;
    conflicting_records_count?: number;
    category?: string;
    approved_intake?: number;
    capacity_overflow_count?: number;
  };
  notice?: string;
}

export interface StudentAdmissionRecord {
  id: string;
  institution_id: string;
  program_id: string;
  academic_year: string;
  masked_apaar_id: string; // Rule 10: Masked, e.g. XXXX-XXXX-1234
  student_name: string;
  date_of_birth: string;
  gender: string;
  email?: string;
  mobile_number?: string;
  admission_number: string;
  admission_date: string;
  category: string;
  quota_type: 'REGULAR' | 'SUPERNUMERARY';
  status:
    | 'PROVISIONAL'
    | 'UNDER_REVIEW'
    | 'CONFIRMED'
    | 'ACTIVE'
    | 'CANCELLED'
    | 'COMPLETED'
    | 'WITHDRAWN'
    | 'MIGRATED'
    | 'SUSPENDED'
    | 'REJECTED';
  version: number;
  l1_status: string;
  l2_status: string;
  l3_status: string;
  verification_summary?: VerificationSummary;
  created_at: string;
  updated_at: string;
}

export interface ReviewCase {
  id: string;
  student_record_id: string;
  institution_id: string;
  case_type: string;
  status: 'OPEN' | 'IN_REVIEW' | 'RESOLVED';
  priority_score: number; // Rule 6: 0 to 100
  score_breakdown: Record<string, number>; // Component weights
  reason_codes: string[];
  match_evidence?: {
    conflicting_records?: Array<{
      record_id: string;
      institution_id: string;
      program_id: string;
      status: string;
      is_cross_institution: boolean;
      masked_apaar: string;
    }>;
    l1_mismatched_fields?: string[];
    l2_reason?: string;
    capacity_overflow_count?: number;
  };
  assigned_reviewer_id?: string;
  resolution?: string;
  resolution_reason?: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
  student_record?: StudentAdmissionRecord;
}

export interface IssuedCredential {
  id: string;
  student_record_id: string;
  institution_id: string;
  program_id: string;
  academic_year: string;
  status: 'ACTIVE' | 'REVOKED';
  is_revoked: boolean;
  verification_uri: string;
  qr_code_base64: string;
  issued_at: string;
  expires_at?: string;
}

export interface PublicVerificationReport {
  is_valid: boolean;
  credential_status: string;
  cryptographic_signature_valid: boolean;
  institution_id: string;
  institution_name: string;
  program_id: string;
  academic_year: string;
  category: string;
  issued_at: string;
  verification_timestamp: string;
  revocation_details?: {
    revoked_at?: string;
    reason?: string;
  };
  synthetic_notice: string;
}

export interface CategorySeatMetric {
  category: string;
  quota_type: string;
  approved_intake: number;
  confirmed_admissions: number;
  utilization_percentage: number;
  is_overfilled: boolean;
}

export interface ProgramSeatMetric {
  program_id: string;
  program_name: string;
  total_approved_intake: number;
  total_confirmed: number;
  utilization_percentage: number;
  category_breakdown: CategorySeatMetric[];
}

export interface VerificationFunnelMetric {
  total_submitted: number;
  confirmed_count: number;
  under_review_count: number;
  provisional_count: number;
  rejected_count: number;
  l1_pass_count: number;
  l1_unavailable_count: number;
  l1_fail_count: number;
  l2_pass_count: number;
  l2_fail_count: number;
  l3_pass_count: number;
  l3_fail_count: number;
}

export interface ReviewQueueSummary {
  total_open_cases: number;
  high_priority_cases: number;
  duplicate_match_cases: number;
  capacity_overflow_cases: number;
  demographic_mismatch_cases: number;
  unapproved_offering_cases: number;
}

export interface SystemOverviewAnalytics {
  total_institutions: number;
  active_institutions: number;
  total_approved_programs: number;
  total_statutory_intake: number;
  total_confirmed_students: number;
  overall_intake_utilization: number;
  funnel: VerificationFunnelMetric;
  review_queue: ReviewQueueSummary;
  program_metrics: ProgramSeatMetric[];
  synthetic_notice: string;
}

export interface InstitutionDashboardAnalytics {
  institution_id: string;
  institution_name: string;
  aicte_permanent_id: string;
  approval_order_number?: string;
  rule_version?: string;
  total_approved_intake: number;
  total_confirmed_students: number;
  utilization_percentage: number;
  funnel: VerificationFunnelMetric;
  programs: ProgramSeatMetric[];
  open_review_cases_count: number;
}

export interface AuditEvent {
  id: string;
  request_id: string;
  actor_id: string;
  actor_role: string;
  institution_id?: string;
  action: string;
  entity_type: string;
  entity_id: string;
  reason: string;
  details?: Record<string, any>;
  ip_address?: string;
  created_at: string;
}

// ---------------- Design System Types ----------------
export type StatusVariant = 'verified' | 'review' | 'critical' | 'unavailable' | 'info';

export type LayerOutcome = 'PASS' | 'FAIL' | 'UNAVAILABLE' | 'SKIPPED' | 'WARNING';

export interface TableColumn<T> {
  key: string;
  header: string;
  accessor?: (row: T) => React.ReactNode;
  sortable?: boolean;
  align?: 'left' | 'center' | 'right';
  width?: string;
}

export interface KpiTrend {
  direction: 'up' | 'down' | 'neutral';
  percentage?: number;
  label?: string;
}

export interface TimelineEvent {
  id: string;
  title: string;
  timestamp: string;
  statusVariant?: StatusVariant;
  statusLabel?: string;
  actor?: string;
  role?: string;
  description?: string;
  details?: Record<string, any>;
}

