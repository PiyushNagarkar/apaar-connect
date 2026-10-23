import React from 'react';
import { X, ShieldCheck, Download, AlertTriangle, ExternalLink, CheckCircle } from 'lucide-react';
import { IssuedCredential } from '../types';

interface QrModalProps {
  credential: IssuedCredential | null;
  onClose: () => void;
}

export const QrModal: React.FC<QrModalProps> = ({ credential, onClose }) => {
  if (!credential) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden border border-slate-200 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-900 via-blue-800 to-indigo-900 text-white p-5 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <ShieldCheck className="w-6 h-6 text-emerald-400" />
            <div>
              <h3 className="font-bold text-base tracking-wide">AICTE Verified Credential</h3>
              <p className="text-xs text-blue-200">Signed & Cryptographically Verifiable</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-blue-200 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 text-center">
          {/* Status Badge */}
          <div className="mb-4 inline-flex items-center space-x-1 px-3 py-1 rounded-full text-xs font-semibold border ${
            credential.is_revoked
              ? 'bg-rose-50 text-rose-700 border-rose-200'
              : 'bg-emerald-50 text-emerald-700 border-emerald-200'
          }">
            {credential.is_revoked ? (
              <>
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>REVOKED</span>
              </>
            ) : (
              <>
                <CheckCircle className="w-3.5 h-3.5" />
                <span>ACTIVE & VALID</span>
              </>
            )}
          </div>

          {/* QR Image */}
          <div className="bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl p-4 inline-block shadow-inner mb-4">
            <img
              src={credential.qr_code_base64}
              alt="AICTE Admission QR Code"
              className="w-48 h-48 mx-auto"
            />
          </div>

          {/* Privacy Minimality Notice (Rule 10) */}
          <div className="bg-blue-50/70 border border-blue-100 rounded-lg p-3 text-left mb-4 text-xs text-blue-950">
            <p className="font-semibold text-blue-900 flex items-center space-x-1">
              <span>Rule 10: Privacy-Minimal Credential</span>
            </p>
            <p className="text-blue-800 mt-0.5">
              Contains no raw APAAR ID or personal contact information. Verifiers authenticate claims purely via digital signature.
            </p>
          </div>

          {/* Credential Details */}
          <div className="text-xs text-left bg-slate-50 rounded-lg p-3 space-y-1.5 font-mono text-slate-700 border border-slate-200">
            <div className="flex justify-between">
              <span className="text-slate-500">Credential ID:</span>
              <span className="font-semibold text-slate-900">{credential.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Student Record:</span>
              <span>{credential.student_record_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Institution:</span>
              <span>{credential.institution_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Academic Year:</span>
              <span>{credential.academic_year}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Issued On:</span>
              <span>{new Date(credential.issued_at).toLocaleDateString()}</span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="bg-slate-50 p-4 border-t border-slate-200 flex justify-end space-x-3">
          <button
            onClick={() => window.print()}
            className="inline-flex items-center space-x-1.5 px-4 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <Download className="w-4 h-4" />
            <span>Download / Print</span>
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-blue-900 text-white rounded-lg text-xs font-semibold hover:bg-blue-800 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
