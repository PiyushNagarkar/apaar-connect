import React, { useEffect, useState } from 'react';
import {
  Building2,
  Upload,
  PlusCircle,
  FileCheck,
  AlertCircle,
  ShieldCheck,
  RefreshCw,
  QrCode,
  Layers,
  CheckCircle,
  X,
  FileText,
} from 'lucide-react';
import {
  InstitutionDashboardAnalytics,
  StudentAdmissionRecord,
  AcademicProgram,
  IssuedCredential,
} from '../types';
import {
  getInstitutionAnalytics,
  getInstitutionPrograms,
  listInstitutionAdmissions,
  submitStudentAdmission,
  submitBatchAdmissions,
  retriggerVerification,
  getStudentCredential,
} from '../services/api';
import { ThreeLayerBadge } from '../components/ThreeLayerBadge';
import { QrModal } from '../components/QrModal';

interface InstitutionPortalProps {
  institutionId?: string;
}

export const InstitutionPortal: React.FC<InstitutionPortalProps> = ({
  institutionId = 'INST-COEP-PUNE',
}) => {
  const [analytics, setAnalytics] = useState<InstitutionDashboardAnalytics | null>(null);
  const [programs, setPrograms] = useState<AcademicProgram[]>([]);
  const [records, setRecords] = useState<StudentAdmissionRecord[]>([]);
  const [selectedProgram, setSelectedProgram] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [qrModalCred, setQrModalCred] = useState<IssuedCredential | null>(null);
  const [inspectedRecord, setInspectedRecord] = useState<StudentAdmissionRecord | null>(null);

  // Form State
  const [formData, setFormData] = useState({
    student_name: '',
    apaar_id: '',
    date_of_birth: '2005-04-15',
    gender: 'M',
    admission_number: '',
    category: 'OPEN',
  });

  const loadData = async () => {
    try {
      setLoading(true);
      const [analyticsData, progs, admissions] = await Promise.all([
        getInstitutionAnalytics(institutionId),
        getInstitutionPrograms(institutionId),
        listInstitutionAdmissions(institutionId, { limit: 50 }),
      ]);
      setAnalytics(analyticsData);
      setPrograms(progs);
      if (progs.length > 0 && !selectedProgram) {
        setSelectedProgram(progs[0].id);
      }
      setRecords(admissions);
    } catch (err) {
      console.error('Error loading institution portal data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [institutionId]);

  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProgram) return;
    try {
      setSubmitting(true);
      await submitStudentAdmission(institutionId, selectedProgram, {
        ...formData,
        admission_date: new Date().toISOString(),
      });
      setModalOpen(false);
      setFormData({
        student_name: '',
        apaar_id: '',
        date_of_birth: '2005-04-15',
        gender: 'M',
        admission_number: '',
        category: 'OPEN',
      });
      await loadData();
    } catch (err: any) {
      alert(`Submission error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRunSampleBatch = async (scenario: 'pass' | 'overflow' | 'duplicate' | 'unavail') => {
    if (!selectedProgram) return;
    try {
      setSubmitting(true);
      let batchItems = [];

      if (scenario === 'pass') {
        batchItems = [
          {
            student_name: 'Ananya Iyer',
            apaar_id: '456789012399',
            date_of_birth: '2005-07-10',
            gender: 'F',
            admission_number: `BATCH-PASS-${Date.now().toString().slice(-4)}`,
            admission_date: new Date().toISOString(),
            category: 'OPEN',
          },
        ];
      } else if (scenario === 'overflow') {
        batchItems = [
          {
            student_name: 'Harsh Vardhan',
            apaar_id: '567890123499',
            date_of_birth: '2004-12-05',
            gender: 'M',
            admission_number: `BATCH-OVERFLOW-${Date.now().toString().slice(-4)}`,
            admission_date: new Date().toISOString(),
            category: 'OPEN', // OPEN is full in COEP CSE, will trigger review case
          },
        ];
      } else if (scenario === 'duplicate') {
        batchItems = [
          {
            student_name: 'Aarav Sharma',
            apaar_id: '123456789012', // Already confirmed elsewhere
            date_of_birth: '2005-04-15',
            gender: 'M',
            admission_number: `BATCH-DUP-${Date.now().toString().slice(-4)}`,
            admission_date: new Date().toISOString(),
            category: 'OPEN',
          },
        ];
      } else if (scenario === 'unavail') {
        batchItems = [
          {
            student_name: 'Siddharth Rao',
            apaar_id: '999900001111', // Simulates upstream gateway timeout (Rule 5)
            date_of_birth: '2005-08-22',
            gender: 'M',
            admission_number: `BATCH-UNAVAIL-${Date.now().toString().slice(-4)}`,
            admission_date: new Date().toISOString(),
            category: 'OPEN',
          },
        ];
      }

      await submitBatchAdmissions(institutionId, {
        program_id: selectedProgram,
        academic_year: '2024-2025',
        students: batchItems,
      });
      await loadData();
    } catch (err: any) {
      alert(`Batch error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetrigger = async (recordId: string) => {
    try {
      await retriggerVerification(recordId);
      await loadData();
    } catch (err: any) {
      alert(`Re-verify error: ${err.message}`);
    }
  };

  const handleViewQr = async (studentId: string) => {
    try {
      const cred = await getStudentCredential(studentId);
      setQrModalCred(cred);
    } catch (err: any) {
      alert(`QR Credential error: ${err.message}`);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  const currentProgMetric = analytics?.programs.find((p) => p.program_id === selectedProgram);
  const regularQuotas = currentProgMetric?.category_breakdown.filter((c) => c.quota_type === 'REGULAR') || [];
  const supernumeraryQuotas = currentProgMetric?.category_breakdown.filter((c) => c.quota_type === 'SUPERNUMERARY') || [];

  return (
    <div className="space-y-6">
      {/* Institution Banner */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center space-x-2">
              <span className="bg-blue-100 text-blue-800 text-[10px] px-2 py-0.5 rounded font-bold font-mono">
                {analytics?.aicte_permanent_id}
              </span>
              <h1 className="text-xl font-bold text-slate-900">{analytics?.institution_name}</h1>
            </div>
            <p className="text-xs text-slate-500 mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span>Approval Order: <strong className="font-mono text-slate-800">{analytics?.approval_order_number || 'AICTE/WR/2024-25/EOA'}</strong></span>
              <span>•</span>
              <span>Rule Version: <strong className="font-mono text-blue-700">{analytics?.rule_version || 'AICTE_2024_25_V1'}</strong></span>
              <span>•</span>
              <span>Approved Intake: <strong className="text-slate-900">{analytics?.total_approved_intake} seats</strong></span>
            </p>
          </div>
          <div className="flex items-center space-x-2 shrink-0">
            <button
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center space-x-1.5 px-3.5 py-2 bg-blue-900 hover:bg-blue-800 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <PlusCircle className="w-4 h-4" />
              <span>Submit Admission</span>
            </button>
            <button
              onClick={loadData}
              className="p-2 border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-lg text-xs"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Program Selector Tabs */}
        <div className="mt-6 pt-4 border-t border-slate-100 flex items-center space-x-2 overflow-x-auto">
          <span className="text-xs font-semibold text-slate-500 shrink-0">Select Program:</span>
          {programs.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelectedProgram(p.id)}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium whitespace-nowrap transition-colors ${
                selectedProgram === p.id
                  ? 'bg-blue-50 text-blue-900 border border-blue-200 font-semibold'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Rule 3 Seat Matrix: Regular vs. Supernumerary Separation */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-bold text-slate-900 text-sm flex items-center space-x-2">
              <Layers className="w-4 h-4 text-blue-600" />
              <span>Sanctioned Category Quotas & Live Consumption (Rule 3)</span>
            </h3>
            <p className="text-xs text-slate-500">
              Per-category non-fungible capacity limits. Regular applicants never absorb supernumerary seats.
            </p>
          </div>
          <span className="text-[11px] font-mono font-semibold px-2.5 py-1 bg-amber-50 text-amber-800 border border-amber-200 rounded">
            Rule 3 Compliant
          </span>
        </div>

        {/* Regular Quotas Grid */}
        <div className="mb-6">
          <p className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-600"></span>
            <span>Regular Category Seats</span>
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {regularQuotas.map((cat) => {
              const pct = cat.utilization_percentage;
              const isFull = cat.confirmed_admissions >= cat.approved_intake;
              return (
                <div
                  key={cat.category}
                  className={`p-3.5 rounded-lg border text-xs ${
                    isFull ? 'bg-amber-50/70 border-amber-200' : 'bg-slate-50 border-slate-200'
                  }`}
                >
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-bold text-slate-900">{cat.category}</span>
                    <span className="font-mono text-slate-600">
                      {cat.confirmed_admissions}/{cat.approved_intake}
                    </span>
                  </div>
                  <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden my-1.5">
                    <div
                      className={`h-full rounded-full ${isFull ? 'bg-amber-600' : 'bg-blue-600'}`}
                      style={{ width: `${Math.min(100, pct)}%` }}
                    ></div>
                  </div>
                  <div className="flex justify-between text-[10px] text-slate-500">
                    <span>{pct}% filled</span>
                    {isFull && <span className="text-amber-700 font-semibold">At Capacity</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Supernumerary Quotas Grid */}
        <div>
          <p className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-600"></span>
            <span>Supernumerary Seats (Isolated & Non-Fungible: TFW, PwD, J&K)</span>
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {supernumeraryQuotas.map((cat) => {
              const pct = cat.utilization_percentage;
              return (
                <div key={cat.category} className="p-3.5 rounded-lg border bg-emerald-50/50 border-emerald-200 text-xs">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-bold text-emerald-950">{cat.category}</span>
                    <span className="font-mono text-emerald-900">
                      {cat.confirmed_admissions}/{cat.approved_intake}
                    </span>
                  </div>
                  <div className="w-full bg-emerald-200 rounded-full h-1.5 overflow-hidden my-1.5">
                    <div
                      className="h-full bg-emerald-600 rounded-full"
                      style={{ width: `${Math.min(100, pct)}%` }}
                    ></div>
                  </div>
                  <span className="text-[10px] text-emerald-700">{pct}% filled • Supernumerary</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Demo Batch Ingestion Quick Runners */}
      <div className="bg-slate-900 text-white rounded-xl p-5 shadow-xs flex flex-col md:flex-row items-center justify-between gap-4">
        <div>
          <h4 className="font-bold text-sm text-slate-100 flex items-center space-x-2">
            <span>Demo Ingestion Scenarios:</span>
            <span className="text-xs font-normal text-slate-400">Run one-click synthetic admission tests</span>
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            Simulate 3-layer verification responses across normal passes, duplicate collisions, and service timeouts.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <button
            disabled={submitting}
            onClick={() => handleRunSampleBatch('pass')}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded text-xs font-semibold transition-colors disabled:opacity-50"
          >
            + Valid Pass
          </button>
          <button
            disabled={submitting}
            onClick={() => handleRunSampleBatch('overflow')}
            className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 rounded text-xs font-semibold transition-colors disabled:opacity-50"
          >
            + Capacity Overflow
          </button>
          <button
            disabled={submitting}
            onClick={() => handleRunSampleBatch('duplicate')}
            className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 rounded text-xs font-semibold transition-colors disabled:opacity-50"
          >
            + Duplicate APAAR
          </button>
          <button
            disabled={submitting}
            onClick={() => handleRunSampleBatch('unavail')}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-xs font-semibold transition-colors disabled:opacity-50"
          >
            + L1 Unavailable (Rule 5)
          </button>
        </div>
      </div>

      {/* Student Admissions Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex items-center justify-between">
          <div>
            <h3 className="font-bold text-slate-900 text-sm">Student Admission Records</h3>
            <p className="text-xs text-slate-500">Live admission records with 3-layer verification status</p>
          </div>
          <span className="text-xs text-slate-500">Showing {records.length} records</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider font-semibold border-b border-slate-200">
              <tr>
                <th className="px-5 py-3">Admission No</th>
                <th className="px-5 py-3">Student Name</th>
                <th className="px-5 py-3">Masked APAAR (Rule 10)</th>
                <th className="px-5 py-3">Category</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">3-Layer Verification</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {records.map((rec) => {
                const isConfirmed = rec.status === 'CONFIRMED' || rec.status === 'ACTIVE';
                const isUnderReview = rec.status === 'UNDER_REVIEW';
                const isProvisional = rec.status === 'PROVISIONAL';

                return (
                  <tr key={rec.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-5 py-3 font-mono font-semibold text-slate-900">{rec.admission_number}</td>
                    <td className="px-5 py-3 font-medium text-slate-900">{rec.student_name}</td>
                    <td className="px-5 py-3 font-mono text-slate-700 bg-slate-50/50">
                      {rec.masked_apaar_id}
                    </td>
                    <td className="px-5 py-3">
                      <span className="font-semibold text-slate-800">{rec.category}</span>
                      <span className="text-[10px] text-slate-500 block">({rec.quota_type})</span>
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          isConfirmed
                            ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                            : isUnderReview
                            ? 'bg-amber-50 text-amber-800 border border-amber-200'
                            : isProvisional
                            ? 'bg-blue-50 text-blue-800 border border-blue-200'
                            : 'bg-rose-50 text-rose-800 border border-rose-200'
                        }`}
                      >
                        {rec.status}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <ThreeLayerBadge
                        l1Status={rec.l1_status}
                        l2Status={rec.l2_status}
                        l3Status={rec.l3_status}
                        size="sm"
                      />
                    </td>
                    <td className="px-5 py-3 text-right space-x-2">
                      <button
                        onClick={() => setInspectedRecord(rec)}
                        className="px-2 py-1 text-[11px] font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded border border-slate-200"
                      >
                        Inspect
                      </button>
                      {isConfirmed && (
                        <button
                          onClick={() => handleViewQr(rec.id)}
                          className="px-2 py-1 text-[11px] font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 rounded border border-blue-200 inline-flex items-center space-x-1"
                        >
                          <QrCode className="w-3 h-3" />
                          <span>QR</span>
                        </button>
                      )}
                      {isProvisional && (
                        <button
                          onClick={() => handleRetrigger(rec.id)}
                          className="px-2 py-1 text-[11px] font-semibold text-blue-700 hover:bg-blue-50 rounded border border-blue-200"
                        >
                          Retry L1
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Single Admission Submission Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-6 border border-slate-200">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200">
              <h3 className="font-bold text-slate-900 text-base">Submit Student Admission Record</h3>
              <button onClick={() => setModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSingleSubmit} className="space-y-4 mt-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Student Full Name</label>
                <input
                  type="text"
                  required
                  value={formData.student_name}
                  onChange={(e) => setFormData({ ...formData, student_name: e.target.value })}
                  placeholder="e.g. Aarav Sharma"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  12-digit APAAR ID (Encrypted via AES-256-GCM, Rule 10)
                </label>
                <input
                  type="text"
                  required
                  maxLength={12}
                  value={formData.apaar_id}
                  onChange={(e) => setFormData({ ...formData, apaar_id: e.target.value })}
                  placeholder="12-digit numeric ID (e.g. 123456789012)"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg font-mono focus:ring-1 focus:ring-blue-500"
                />
                <p className="text-[10px] text-slate-500 mt-1">
                  Note: APAAR ID is encrypted on arrival. Never stored in plaintext and never leaked in URLs or QR codes.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Date of Birth</label>
                  <input
                    type="date"
                    required
                    value={formData.date_of_birth}
                    onChange={(e) => setFormData({ ...formData, date_of_birth: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Gender</label>
                  <select
                    value={formData.gender}
                    onChange={(e) => setFormData({ ...formData, gender: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                  >
                    <option value="M">Male (M)</option>
                    <option value="F">Female (F)</option>
                    <option value="OTHER">Other</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Local Enrollment / Roll No</label>
                  <input
                    type="text"
                    required
                    value={formData.admission_number}
                    onChange={(e) => setFormData({ ...formData, admission_number: e.target.value })}
                    placeholder="e.g. COEP-2024-088"
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Admitted Category</label>
                  <select
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                  >
                    <optgroup label="Regular Intake (Rule 3)">
                      <option value="OPEN">OPEN (General)</option>
                      <option value="OBC_NCL">OBC-NCL</option>
                      <option value="SC">SC</option>
                      <option value="ST">ST</option>
                      <option value="EWS">EWS</option>
                    </optgroup>
                    <optgroup label="Supernumerary (Isolated Quota)">
                      <option value="TFW">TFW (Tuition Fee Waiver)</option>
                      <option value="PWD">PwD (Persons with Disabilities)</option>
                      <option value="JK_MIGRANT">J&K Migrant</option>
                    </optgroup>
                  </select>
                </div>
              </div>

              <div className="pt-4 border-t border-slate-200 flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="px-4 py-2 border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 disabled:opacity-50"
                >
                  {submitting ? 'Verifying Layers...' : 'Submit & Verify'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Inspector Modal */}
      {inspectedRecord && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-xl w-full p-6 border border-slate-200 text-xs">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div>
                <h3 className="font-bold text-slate-900 text-base">3-Layer Verification Breakdown</h3>
                <p className="text-slate-500 font-mono">{inspectedRecord.id} • {inspectedRecord.student_name}</p>
              </div>
              <button onClick={() => setInspectedRecord(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              {/* L1 Inspector */}
              <div className="p-3.5 rounded-lg border bg-slate-50 space-y-1">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-800">L1 Identity Verification (MOCK_APAAR_V1)</span>
                  <span className="font-bold uppercase text-[10px] px-2 py-0.5 rounded bg-white border">
                    {inspectedRecord.l1_status}
                  </span>
                </div>
                <p className="text-slate-600">
                  Adapter: {inspectedRecord.verification_summary?.l1?.adapter_version || 'MOCK_APAAR_V1'}
                </p>
                <p className="text-slate-600">
                  Confidence Score: {inspectedRecord.verification_summary?.l1?.confidence_score ?? 'N/A'}
                </p>
                {inspectedRecord.verification_summary?.l1?.reason_message && (
                  <p className="text-slate-700 italic">"{inspectedRecord.verification_summary.l1.reason_message}"</p>
                )}
              </div>

              {/* L2 Inspector */}
              <div className="p-3.5 rounded-lg border bg-slate-50 space-y-1">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-800">L2 Institutional Authority</span>
                  <span className="font-bold uppercase text-[10px] px-2 py-0.5 rounded bg-white border">
                    {inspectedRecord.l2_status}
                  </span>
                </div>
                <p className="text-slate-600">
                  Order: {inspectedRecord.verification_summary?.l2?.order_number || 'AICTE Frozen Snapshot'}
                </p>
                <p className="text-slate-600">
                  Sanctioned Intake: {inspectedRecord.verification_summary?.l2?.approved_intake ?? 'Confirmed'}
                </p>
              </div>

              {/* L3 Inspector */}
              <div className="p-3.5 rounded-lg border bg-slate-50 space-y-1">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-800">L3 Admission & Seat Compliance (Rule 3 & 4)</span>
                  <span className="font-bold uppercase text-[10px] px-2 py-0.5 rounded bg-white border">
                    {inspectedRecord.l3_status}
                  </span>
                </div>
                <p className="text-slate-600">
                  Category: {inspectedRecord.category} ({inspectedRecord.quota_type})
                </p>
                <p className="text-slate-600">
                  Duplicate Match: {inspectedRecord.verification_summary?.l3?.is_duplicate ? 'Detected (Opened Review Case)' : 'None'}
                </p>
              </div>
            </div>

            <div className="mt-5 pt-3 border-t border-slate-200 flex justify-end">
              <button
                onClick={() => setInspectedRecord(null)}
                className="px-4 py-2 bg-slate-900 text-white rounded-lg font-semibold hover:bg-slate-800"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* QR Modal */}
      <QrModal credential={qrModalCred} onClose={() => setQrModalCred(null)} />
    </div>
  );
};
