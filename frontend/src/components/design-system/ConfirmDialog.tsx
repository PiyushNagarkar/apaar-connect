import React, { useState, useEffect } from 'react';
import { AlertTriangle, ShieldCheck, X, Loader2 } from 'lucide-react';

export interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning' | 'primary';
  reasonLabel?: string;
  reasonPlaceholder?: string;
  minReasonLength?: number;
  onConfirm: (reason: string) => void | Promise<void>;
  onClose: () => void;
  isLoading?: boolean;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  description,
  confirmLabel = 'Confirm Action',
  cancelLabel = 'Cancel',
  variant = 'danger',
  reasonLabel = 'Statutory Justification / Audit Reason',
  reasonPlaceholder = 'Specify regulatory or administrative justification (mandatory)...',
  minReasonLength = 5,
  onConfirm,
  onClose,
  isLoading = false,
}) => {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setReason('');
      setError(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const trimmedReason = reason.trim();
  const isValid = trimmedReason.length >= minReasonLength;

  const handleConfirm = async () => {
    if (!isValid) {
      setError(`A clear justification of at least ${minReasonLength} characters is required for regulatory audit logging.`);
      return;
    }
    setError(null);
    await onConfirm(trimmedReason);
  };

  const variantStyles = {
    danger: {
      headerBg: 'bg-rose-50 text-rose-900 border-b border-rose-200',
      iconBg: 'bg-rose-100 text-rose-700',
      confirmBtn: 'bg-rose-700 hover:bg-rose-800 text-white focus-visible:ring-rose-600',
      icon: AlertTriangle,
    },
    warning: {
      headerBg: 'bg-amber-50 text-amber-900 border-b border-amber-200',
      iconBg: 'bg-amber-100 text-amber-700',
      confirmBtn: 'bg-amber-700 hover:bg-amber-800 text-white focus-visible:ring-amber-600',
      icon: AlertTriangle,
    },
    primary: {
      headerBg: 'bg-blue-50 text-blue-900 border-b border-blue-200',
      iconBg: 'bg-blue-100 text-blue-700',
      confirmBtn: 'bg-blue-900 hover:bg-blue-950 text-white focus-visible:ring-blue-700',
      icon: ShieldCheck,
    },
  }[variant];

  const IconComponent = variantStyles.icon;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
    >
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        {/* Header */}
        <div className={`px-6 py-4 flex items-center justify-between ${variantStyles.headerBg}`}>
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg shrink-0 ${variantStyles.iconBg}`}>
              <IconComponent className="w-5 h-5" aria-hidden="true" />
            </div>
            <h2 id="confirm-dialog-title" className="text-base font-bold tracking-tight">
              {title}
            </h2>
          </div>
          <button
            type="button"
            disabled={isLoading}
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 rounded-lg p-1 transition-colors"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">{description}</p>

          {/* Audit Notice Box */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700 space-y-1">
            <div className="flex items-center gap-1.5 font-bold text-slate-900">
              <ShieldCheck className="w-4 h-4 text-blue-800" />
              <span>Immutable Regulatory Audit Record</span>
            </div>
            <p className="text-[11px] text-slate-500">
              Pursuant to Rule 9, your reason will be cryptographically bound with your active Actor ID,
              role, and timestamp in the SHA-256 tamper-evident log chain.
            </p>
          </div>

          {/* Reason Input */}
          <div>
            <label htmlFor="confirm-reason" className="block text-xs font-bold text-slate-800 mb-1.5">
              {reasonLabel} <span className="text-rose-600 font-bold">*</span>
            </label>
            <textarea
              id="confirm-reason"
              rows={3}
              disabled={isLoading}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                if (error) setError(null);
              }}
              placeholder={reasonPlaceholder}
              className={`w-full p-2.5 text-xs sm:text-sm bg-white border rounded-md shadow-2xs focus:outline-none focus:ring-2 transition-colors ${
                error
                  ? 'border-rose-400 focus:ring-rose-500'
                  : 'border-slate-300 focus:ring-blue-800 focus:border-blue-800'
              }`}
            />
            <div className="flex items-center justify-between mt-1 text-[11px]">
              {error ? (
                <span className="text-rose-600 font-semibold">{error}</span>
              ) : (
                <span className="text-slate-400">
                  Minimum {minReasonLength} characters required
                </span>
              )}
              <span className={trimmedReason.length < minReasonLength ? 'text-slate-400' : 'text-emerald-700 font-semibold'}>
                {trimmedReason.length}/{minReasonLength} min
              </span>
            </div>
          </div>
        </div>

        {/* Footer Buttons */}
        <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex items-center justify-end gap-3">
          <button
            type="button"
            disabled={isLoading}
            onClick={onClose}
            className="px-4 py-2 text-xs sm:text-sm font-semibold text-slate-700 hover:text-slate-900 hover:bg-slate-200/60 rounded-md transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={!isValid || isLoading}
            onClick={handleConfirm}
            className={`inline-flex items-center gap-2 px-4 py-2 text-xs sm:text-sm font-bold rounded-md shadow-xs transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${variantStyles.confirmBtn}`}
          >
            {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            <span>{confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
