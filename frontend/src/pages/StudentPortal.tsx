import React, { useEffect, useState } from 'react';
import {
  ShieldCheck,
  QrCode,
  Download,
  AlertCircle,
  Building,
  GraduationCap,
  Calendar,
  CheckCircle,
  Clock,
  RefreshCw,
} from 'lucide-react';
import { StudentAdmissionRecord, IssuedCredential } from '../types';
import { listInstitutionAdmissions, getStudentCredential } from '../services/api';
import { QrModal } from '../components/QrModal';

export const StudentPortal: React.FC = () => {
  const [student, setStudent] = useState<StudentAdmissionRecord | null>(null);
  const [credential, setCredential] = useState<IssuedCredential | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [qrModalOpen, setQrModalOpen] = useState<boolean>(false);

  useEffect(() => {
    const fetchStudent = async () => {
      try {
        setLoading(true);
        // Load demo confirmed student Aarav Sharma from COEP
        const records = await listInstitutionAdmissions('INST-COEP-PUNE', { limit: 10 });
        const confirmed = records.find((r) => r.status === 'CONFIRMED' || r.status === 'ACTIVE') || records[0];
        if (confirmed) {
          setStudent(confirmed);
          try {
            const cred = await getStudentCredential(confirmed.id);
            setCredential(cred);
          } catch (e) {
            console.log('No credential found yet');
          }
        }
      } catch (err) {
        console.error('Error fetching student portal:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchStudent();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[350px]">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (!student) {
    return (
      <div className="bg-white p-8 rounded-xl border border-slate-200 text-center">
        <p className="text-sm text-slate-500">No active student record found.</p>
      </div>
    );
  }

  const isVerified = student.status === 'CONFIRMED' || student.status === 'ACTIVE';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Student Welcome Header */}
      <div className="bg-gradient-to-r from-blue-900 via-blue-800 to-indigo-950 text-white rounded-2xl p-6 shadow-md relative overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 relative z-10">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-blue-300">
              AICTE National Student Portal
            </span>
            <h1 className="text-2xl font-bold mt-1 text-white">{student.student_name}</h1>
            <p className="text-xs text-blue-200 mt-1">
              Admission Number: <strong className="font-mono text-white">{student.admission_number}</strong>
            </p>
          </div>

          <div className="shrink-0">
            {isVerified ? (
              <span className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <span>AICTE VERIFIED ADMISSION</span>
              </span>
            ) : (
              <span className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-400/40">
                <Clock className="w-4 h-4 text-amber-400" />
                <span>STATUS: {student.status}</span>
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Profile Card */}
        <div className="md:col-span-2 bg-white rounded-xl border border-slate-200 p-6 shadow-xs space-y-4 text-xs">
          <h3 className="font-bold text-slate-900 text-sm border-b border-slate-100 pb-3">
            Academic Enrollment Information
          </h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-slate-500 block mb-0.5">Institution Code:</span>
              <span className="font-semibold text-slate-800">{student.institution_id}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5">Academic Year:</span>
              <span className="font-semibold text-slate-800">{student.academic_year}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5">Program ID:</span>
              <span className="font-semibold text-slate-800">{student.program_id}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5">Admission Category:</span>
              <span className="font-semibold text-slate-800">
                {student.category} ({student.quota_type})
              </span>
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 bg-slate-50 p-3 rounded-lg space-y-1">
            <span className="text-slate-500 block">Masked APAAR ID (Rule 10):</span>
            <span className="font-mono text-base font-bold text-blue-900 tracking-wider">
              {student.masked_apaar_id}
            </span>
            <p className="text-[10px] text-slate-500">
              Raw APAAR is encrypted via AES-256-GCM and never displayed in full or shared in public verifier payloads.
            </p>
          </div>

          {/* 3-Layer Summary */}
          <div className="pt-3 border-t border-slate-100">
            <span className="text-slate-500 block mb-2 font-semibold">Verification Layers:</span>
            <div className="grid grid-cols-3 gap-2 text-center text-[11px]">
              <div className="p-2 bg-emerald-50 text-emerald-800 rounded border border-emerald-200">
                <span className="block font-bold">L1 Identity</span>
                <span>{student.l1_status} (MOCK)</span>
              </div>
              <div className="p-2 bg-emerald-50 text-emerald-800 rounded border border-emerald-200">
                <span className="block font-bold">L2 Authority</span>
                <span>{student.l2_status} (Snapshot)</span>
              </div>
              <div className="p-2 bg-emerald-50 text-emerald-800 rounded border border-emerald-200">
                <span className="block font-bold">L3 Seats</span>
                <span>{student.l3_status} (Compliance)</span>
              </div>
            </div>
          </div>
        </div>

        {/* Digital QR Credential Card */}
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs flex flex-col justify-between items-center text-center">
          <div>
            <div className="p-3 bg-blue-50 text-blue-900 rounded-full inline-block mb-3">
              <QrCode className="w-6 h-6" />
            </div>
            <h3 className="font-bold text-slate-900 text-sm">Privacy-Minimal Credential</h3>
            <p className="text-xs text-slate-500 mt-1">
              Signed digital badge verifiable by any third-party employer or registrar.
            </p>
          </div>

          {credential ? (
            <div className="my-4">
              <div className="p-2 border border-slate-200 rounded-lg inline-block bg-slate-50 shadow-inner">
                <img
                  src={credential.qr_code_base64}
                  alt="Student QR Credential"
                  className="w-32 h-32"
                />
              </div>
              <p className="text-[10px] text-slate-500 mt-1 font-mono">{credential.id}</p>
            </div>
          ) : (
            <div className="my-6 p-4 bg-slate-50 rounded-lg text-xs text-slate-500">
              Credential will be generated once verified.
            </div>
          )}

          {credential && (
            <button
              onClick={() => setQrModalOpen(true)}
              className="w-full py-2 px-3 bg-blue-900 hover:bg-blue-800 text-white font-semibold rounded-lg text-xs shadow-xs transition-colors flex items-center justify-center space-x-1.5"
            >
              <span>View Full Credential</span>
            </button>
          )}
        </div>
      </div>

      <QrModal credential={qrModalOpen ? credential : null} onClose={() => setQrModalOpen(false)} />
    </div>
  );
};
