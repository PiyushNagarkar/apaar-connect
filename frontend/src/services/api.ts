import {
  SystemRole,
  SystemOverviewAnalytics,
  InstitutionDashboardAnalytics,
  Institution,
  AcademicProgram,
  SeatCategoryCapacity,
  ApprovalSnapshot,
  StudentAdmissionRecord,
  ReviewCase,
  IssuedCredential,
  PublicVerificationReport,
  AuditEvent,
} from '../types';

let currentRole: SystemRole = 'AICTE_ADMIN';
let currentInstitutionId: string = 'INST-COEP-PUNE';
let currentUserId: string = 'user-aicte-admin-01';
let currentStudentId: string = '';

export function setApiAuthContext(
  role: SystemRole,
  institutionId?: string,
  userId?: string,
  studentId?: string,
) {
  currentRole = role;
  if (institutionId !== undefined) currentInstitutionId = institutionId;
  if (userId !== undefined) currentUserId = userId;
  if (studentId !== undefined) currentStudentId = studentId;
}

const API_BASE = '/api/v1';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  // Inject mock headers for server-side role and institutional scoping (Rule 7)
  headers.set('X-Mock-Role', currentRole);
  if (currentInstitutionId) headers.set('X-Mock-Institution-Id', currentInstitutionId);
  if (currentUserId) headers.set('X-Mock-User-Id', currentUserId);
  if (currentStudentId) headers.set('X-Mock-Student-Id', currentStudentId);

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    const message = errorData.message || `Request failed with status ${res.status}`;
    const error = new Error(message) as any;
    error.status = res.status;
    error.code = errorData.code;
    error.details = errorData.details;
    throw error;
  }

  return res.json();
}

// ---------------- Analytics (Rule 11) ----------------
export async function getSystemOverview(): Promise<SystemOverviewAnalytics> {
  return request<SystemOverviewAnalytics>('/analytics/overview');
}

export async function getInstitutionAnalytics(institutionId: string): Promise<InstitutionDashboardAnalytics> {
  return request<InstitutionDashboardAnalytics>(`/analytics/institution/${institutionId}`);
}

// ---------------- Institutions & Approvals (Rule 3, 7, 8) ----------------
export async function listInstitutions(): Promise<Institution[]> {
  return request<Institution[]>('/institutions');
}

export async function getInstitution(institutionId: string): Promise<Institution> {
  return request<Institution>(`/institutions/${institutionId}`);
}

export async function getInstitutionPrograms(institutionId: string): Promise<AcademicProgram[]> {
  return request<AcademicProgram[]>(`/institutions/${institutionId}/programs`);
}

export async function getActiveSnapshot(institutionId: string): Promise<ApprovalSnapshot> {
  return request<ApprovalSnapshot>(`/institutions/${institutionId}/snapshots/active`);
}

export async function getSeatCapacities(institutionId: string, programId?: string): Promise<SeatCategoryCapacity[]> {
  const query = programId ? `?program_id=${programId}` : '';
  return request<SeatCategoryCapacity[]>(`/institutions/${institutionId}/seat-capacities${query}`);
}

// ---------------- Admissions & Records (Rules 1, 3, 4, 5, 8, 10, 12) ----------------
export async function listInstitutionAdmissions(
  institutionId: string,
  params?: { programId?: string; status?: string; category?: string; limit?: number },
): Promise<StudentAdmissionRecord[]> {
  const q = new URLSearchParams();
  if (params?.programId) q.set('program_id', params.programId);
  if (params?.status) q.set('status', params.status);
  if (params?.category) q.set('category', params.category);
  if (params?.limit) q.set('limit', String(params.limit));
  return request<StudentAdmissionRecord[]>(`/institutions/${institutionId}/admissions?${q.toString()}`);
}

export async function getAdmissionRecord(recordId: string): Promise<StudentAdmissionRecord> {
  return request<StudentAdmissionRecord>(`/admissions/${recordId}`);
}

export async function submitStudentAdmission(
  institutionId: string,
  programId: string,
  data: any,
  academicYear: string = '2024-2025',
): Promise<StudentAdmissionRecord> {
  return request<StudentAdmissionRecord>(
    `/institutions/${institutionId}/admissions?program_id=${programId}&academic_year=${academicYear}`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    },
  );
}

export async function submitBatchAdmissions(
  institutionId: string,
  batch: { program_id: string; academic_year: string; students: any[] },
): Promise<any> {
  return request<any>(`/institutions/${institutionId}/admissions/batch`, {
    method: 'POST',
    body: JSON.stringify(batch),
  });
}

export async function retriggerVerification(recordId: string): Promise<StudentAdmissionRecord> {
  return request<StudentAdmissionRecord>(`/admissions/${recordId}/verify`, { method: 'POST' });
}

export async function transitionLifecycle(
  recordId: string,
  targetStatus: string,
  reason: string,
): Promise<StudentAdmissionRecord> {
  return request<StudentAdmissionRecord>(`/admissions/${recordId}/transition`, {
    method: 'POST',
    body: JSON.stringify({ target_status: targetStatus, reason }),
  });
}

// ---------------- Human Review Cases (Rules 4, 6) ----------------
export async function listReviewCases(status: string = 'OPEN', institutionId?: string): Promise<ReviewCase[]> {
  const q = new URLSearchParams();
  if (status) q.set('status', status);
  if (institutionId) q.set('institution_id', institutionId);
  return request<ReviewCase[]>(`/reviews/cases?${q.toString()}`);
}

export async function getReviewCase(caseId: string): Promise<ReviewCase> {
  return request<ReviewCase>(`/reviews/cases/${caseId}`);
}

export async function resolveReviewCase(
  caseId: string,
  resolution: 'CONFIRMED' | 'PROVISIONAL' | 'REJECTED',
  reason: string,
): Promise<ReviewCase> {
  return request<ReviewCase>(`/reviews/cases/${caseId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ resolution, reason }),
  });
}

// ---------------- Credentials & Public QR Verification (Rule 10) ----------------
export async function getStudentCredential(studentRecordId: string): Promise<IssuedCredential> {
  return request<IssuedCredential>(`/credentials/student/${studentRecordId}`);
}

export async function issueCredential(studentRecordId: string): Promise<IssuedCredential> {
  return request<IssuedCredential>(`/credentials/issue/${studentRecordId}`, { method: 'POST' });
}

export async function revokeCredential(credentialId: string, reason: string): Promise<IssuedCredential> {
  return request<IssuedCredential>(`/credentials/${credentialId}/revoke`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function verifyCredentialPublic(tokenOrId: string): Promise<PublicVerificationReport> {
  return request<PublicVerificationReport>(`/credentials/verify/${tokenOrId}`);
}

// ---------------- Audit Trail (Rule 9) ----------------
export async function getAuditEvents(limit: number = 50): Promise<AuditEvent[]> {
  return request<AuditEvent[]>(`/audit/events?limit=${limit}`);
}
