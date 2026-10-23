import React, { useState } from 'react';
import { Eye, EyeOff, Copy, Check, Shield } from 'lucide-react';

export interface MaskedValueProps {
  value: string;
  type?: 'apaar' | 'aadhaar' | 'phone' | 'email' | 'generic';
  label?: string;
  allowReveal?: boolean;
  onRevealLogged?: (val: string) => void;
  className?: string;
}

export function maskSensitiveData(
  val: string,
  type: 'apaar' | 'aadhaar' | 'phone' | 'email' | 'generic' = 'apaar',
): string {
  if (!val) return '—';
  const clean = val.replace(/\s+/g, '');

  if (type === 'apaar' || type === 'aadhaar') {
    if (clean.length >= 4) {
      const last4 = clean.slice(-4);
      return `XXXX-XXXX-${last4}`;
    }
    return 'XXXX-XXXX-XXXX';
  }

  if (type === 'phone') {
    if (clean.length >= 4) {
      const last4 = clean.slice(-4);
      return `+91-XXXXX-${last4}`;
    }
    return '+91-XXXXX-XXXXX';
  }

  if (type === 'email') {
    const parts = val.split('@');
    if (parts.length === 2) {
      const [user, domain] = parts;
      const maskedUser = user.length > 2 ? `${user.slice(0, 2)}***` : `${user}***`;
      return `${maskedUser}@${domain}`;
    }
    return '***@domain.com';
  }

  // Generic
  if (val.length > 6) {
    return `${val.slice(0, 2)}••••${val.slice(-2)}`;
  }
  return '••••••';
}

export const MaskedValue: React.FC<MaskedValueProps> = ({
  value,
  type = 'apaar',
  label,
  allowReveal = true,
  onRevealLogged,
  className = '',
}) => {
  const [isRevealed, setIsRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showNotice, setShowNotice] = useState(false);

  const displayMasked = maskSensitiveData(value, type);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const handleToggleReveal = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isRevealed) {
      // Log read access event pursuant to DPDP Act 2023 & Section 7
      onRevealLogged?.(value);
      setShowNotice(true);
      setTimeout(() => setShowNotice(false), 4000);
    }
    setIsRevealed(!isRevealed);
  };

  return (
    <div className={`inline-flex flex-col gap-1 ${className}`}>
      {label && (
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
          {label}
        </span>
      )}

      <div className="inline-flex items-center gap-1.5 p-1 bg-slate-100/90 rounded-md border border-slate-200 text-xs font-mono select-none group">
        <span className="px-1.5 text-slate-900 font-medium">
          {isRevealed ? value : displayMasked}
        </span>

        {/* Copy Button */}
        <button
          type="button"
          onClick={handleCopy}
          title={copied ? 'Copied to clipboard' : 'Copy value'}
          className="p-1 text-slate-400 hover:text-slate-700 rounded hover:bg-slate-200/70 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-blue-700"
          aria-label="Copy sensitive value"
        >
          {copied ? (
            <Check className="w-3.5 h-3.5 text-emerald-600" />
          ) : (
            <Copy className="w-3.5 h-3.5" />
          )}
        </button>

        {/* Reveal / Unmask Button */}
        {allowReveal && (
          <button
            type="button"
            onClick={handleToggleReveal}
            title={
              isRevealed
                ? 'Mask sensitive value'
                : 'Unmask value (Read access recorded in privacy log)'
            }
            className={`p-1 rounded transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-blue-700 ${
              isRevealed
                ? 'text-blue-700 hover:bg-blue-100'
                : 'text-slate-400 hover:text-slate-700 hover:bg-slate-200/70'
            }`}
            aria-label={isRevealed ? 'Mask value' : 'Unmask value'}
          >
            {isRevealed ? (
              <EyeOff className="w-3.5 h-3.5" />
            ) : (
              <Eye className="w-3.5 h-3.5" />
            )}
          </button>
        )}
      </div>

      {showNotice && (
        <span className="text-[10px] text-amber-800 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 flex items-center gap-1 animate-in fade-in">
          <Shield className="w-3 h-3 text-amber-700 shrink-0" />
          <span>DPDP Act audit: Unmask read access logged.</span>
        </span>
      )}
    </div>
  );
};

export default MaskedValue;
