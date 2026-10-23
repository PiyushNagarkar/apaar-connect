import React, { useState } from 'react';
import {
  ScanLine,
  ShieldCheck,
  ShieldAlert,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Search,
  KeyRound,
  Building,
  GraduationCap,
  Calendar,
  Lock,
} from 'lucide-react';
import { PublicVerificationReport } from '../types';
import { verifyCredentialPublic } from '../services/api';

export const PublicVerifier: React.FC = () => {
  const [tokenInput, setTokenInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [report, setReport] = useState<PublicVerificationReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleVerify = async (e?: React.FormEvent, customToken?: string) => {
    if (e) e.preventDefault();
    const token = customToken || tokenInput;
    if (!token.trim()) return;

    try {
      setLoading(true);
      setError(null);
      setReport(null);
      const res = await verifyCredentialPublic(token.trim());
      setReport(res);
    } catch (err: any) {
      setError(err.message || 'Verification failed. Token not found or malformed.');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickTest = (token: string) => {
    setTokenInput(token);
    handleVerify(undefined, token);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs text-center space-y-2">
        <div className="p-3 bg-blue-50 text-blue-900 rounded-full inline-block">
          <ScanLine className="w-8 h-8" />
        </div>
        <h1 className="text-xl font-bold text-slate-900">AICTE Public Credential Verifier</h1>
        <p className="text-xs text-slate-500 max-w-lg mx-auto">
          Verify the cryptographic authenticity and regulatory status of any AICTE student credential in real-time.
        </p>

        {/* Quick Test Demo Presets */}
        <div className="pt-3 flex flex-wrap items-center justify-center gap-2">
          <span className="text-[11px] font-semibold text-slate-400">Quick Test Samples:</span>
          <button
            onClick={() => handleQuickTest('CRED-')}
            className="px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-mono rounded"
          >
            Autodetect Active Credential
          </button>
        </div>
      </div>

      {/* Verification Input Form */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs">
        <form onSubmit={(e) => handleVerify(e)} className="space-y-3">
          <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
            Credential ID or Scanned QR Token:
          </label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                required
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Enter Credential ID (e.g. CRED-...) or raw signed token"
                className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-xs font-mono focus:ring-1 focus:ring-blue-600 focus:outline-hidden"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-5 py-2.5 bg-blue-900 hover:bg-blue-800 text-white rounded-lg text-xs font-bold shadow-xs transition-colors shrink-0 disabled:opacity-50"
            >
              {loading ? 'Verifying...' : 'Verify Credential'}
            </button>
          </div>
        </form>
      </div>

      {/* Error Output */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 p-5 rounded-xl text-xs text-rose-800 flex items-start space-x-3 animate-in fade-in">
          <XCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <h4 className="font-bold text-rose-900">Credential Verification Failed</h4>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Verification Success / Report Card */}
      {report && (
        <div
          className={`rounded-2xl border p-6 shadow-md transition-all animate-in fade-in zoom-in-95 ${
            report.is_valid
              ? 'bg-white border-emerald-300 ring-2 ring-emerald-500/10'
              : 'bg-white border-rose-300 ring-2 ring-rose-500/10'
          }`}
        >
          {/* Header Banner */}
          <div className="flex items-center justify-between pb-4 border-b border-slate-100">
            <div className="flex items-center space-x-3">
              {report.is_valid ? (
                <div className="p-2.5 rounded-full bg-emerald-100 text-emerald-700">
                  <CheckCircle className="w-6 h-6" />
                </div>
              ) : (
                <div className="p-2.5 rounded-full bg-rose-100 text-rose-700">
                  <AlertTriangle className="w-6 h-6" />
                </div>
              )}
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  {report.is_valid ? 'Legitimate AICTE Credential' : 'Invalid or Revoked Credential'}
                </h3>
                <p className="text-xs text-slate-500">
                  Verification Timestamp: {new Date(report.verification_timestamp).toLocaleString()}
                </p>
              </div>
            </div>

            <span
              className={`px-3 py-1 rounded-full text-xs font-extrabold uppercase tracking-wider ${
                report.credential_status === 'ACTIVE'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                  : 'bg-rose-50 text-rose-800 border border-rose-200'
              }`}
            >
              {report.credential_status}
            </span>
          </div>

          {/* Revocation Warning Box if Revoked */}
          {report.revocation_details && (
            <div className="mt-4 p-3.5 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-900">
              <p className="font-bold flex items-center space-x-1.5">
                <AlertTriangle className="w-4 h-4 text-rose-600" />
                <span>Regulatory Revocation Recorded</span>
              </p>
              <p className="mt-1">
                Reason: <strong>{report.revocation_details.reason}</strong>
              </p>
              {report.revocation_details.revoked_at && (
                <p className="text-[11px] text-rose-700 mt-0.5">
                  Revoked on: {new Date(report.revocation_details.revoked_at).toLocaleString()}
                </p>
              )}
            </div>
          )}

          {/* Claim Details */}
          <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-3 bg-slate-50 rounded-lg space-y-1">
              <span className="text-slate-500 block">Institution:</span>
              <span className="font-bold text-slate-900">{report.institution_name}</span>
              <span className="font-mono text-[11px] text-slate-500 block">({report.institution_id})</span>
            </div>

            <div className="p-3 bg-slate-50 rounded-lg space-y-1">
              <span className="text-slate-500 block">Academic Session:</span>
              <span className="font-bold text-slate-900">{report.academic_year}</span>
              <span className="text-[11px] text-slate-600 block">Program: {report.program_id}</span>
            </div>

            <div className="p-3 bg-slate-50 rounded-lg space-y-1">
              <span className="text-slate-500 block">Admission Quota Category:</span>
              <span className="font-bold text-slate-900">{report.category}</span>
            </div>

            <div className="p-3 bg-slate-50 rounded-lg space-y-1">
              <span className="text-slate-500 block">Cryptographic Signature:</span>
              <span className="font-bold text-emerald-700 flex items-center space-x-1">
                <CheckCircle className="w-3.5 h-3.5" />
                <span>HMAC-SHA256 Authenticated</span>
              </span>
            </div>
          </div>

          {/* Privacy Guarantee (Rule 10) */}
          <div className="mt-5 pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span className="flex items-center space-x-1">
              <Lock className="w-3.5 h-3.5 text-blue-600" />
              <span>Rule 10: Zero Identity Leakage Guarantee (No APAAR in payload)</span>
            </span>
            <span className="italic">{report.synthetic_notice}</span>
          </div>
        </div>
      )}
    </div>
  );
};
