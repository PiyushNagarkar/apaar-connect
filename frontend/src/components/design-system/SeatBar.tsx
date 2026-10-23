import React from 'react';
import { AlertOctagon, CheckCircle2, ShieldCheck, AlertTriangle } from 'lucide-react';
import { StatusChip } from './StatusChip';

export interface SeatBarProps {
  category: string;
  quotaType?: 'REGULAR' | 'SUPERNUMERARY' | string;
  approved: number;
  occupied: number;
  provisional?: number;
  showDetails?: boolean;
  className?: string;
}

export const SeatBar: React.FC<SeatBarProps> = ({
  category,
  quotaType = 'REGULAR',
  approved,
  occupied,
  provisional = 0,
  showDetails = true,
  className = '',
}) => {
  const isSupernumerary = quotaType.toUpperCase().includes('SUPERNUMERARY') ||
    ['TFW', 'EWS', 'FN', 'PIO', 'JK_MIGRANT'].some((q) => category.toUpperCase().includes(q));

  const totalCommitted = occupied + provisional;
  const isZeroApproval = approved === 0;
  const isExceeded = isZeroApproval ? totalCommitted > 0 : totalCommitted > approved;
  const isAtLimit = !isExceeded && totalCommitted === approved && approved > 0;
  const isNearLimit = !isExceeded && !isAtLimit && approved > 0 && totalCommitted >= approved * 0.9;

  // Percentage calculations
  const occupiedPct = approved > 0 ? Math.min(100, (occupied / approved) * 100) : occupied > 0 ? 100 : 0;
  const provisionalPct = approved > 0 ? Math.min(100 - occupiedPct, (provisional / approved) * 100) : 0;
  const remaining = Math.max(0, approved - totalCommitted);
  const overage = isExceeded ? totalCommitted - approved : 0;

  return (
    <div
      className={`p-4 bg-white rounded-lg border transition-all ${
        isExceeded
          ? 'border-rose-300 bg-rose-50/20 shadow-xs'
          : isAtLimit
          ? 'border-amber-300 bg-amber-50/10'
          : 'border-slate-200 shadow-2xs'
      } ${className}`}
      role="region"
      aria-label={`Seat matrix for ${category}`}
    >
      {/* Header Info */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="font-bold text-xs sm:text-sm text-slate-900 tracking-tight">
            {category}
          </span>
          <span
            className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded border ${
              isSupernumerary
                ? 'bg-purple-50 text-purple-800 border-purple-200'
                : 'bg-slate-100 text-slate-700 border-slate-200'
            }`}
          >
            {isSupernumerary ? 'Supernumerary Quota' : 'Regular Intake'}
          </span>
        </div>

        <div>
          {isExceeded ? (
            <StatusChip
              variant="critical"
              label={`Capacity Exceeded (+${overage})`}
              size="sm"
              icon={AlertOctagon}
            />
          ) : isAtLimit ? (
            <StatusChip
              variant="review"
              label="100% At Limit"
              size="sm"
              icon={AlertTriangle}
            />
          ) : isNearLimit ? (
            <StatusChip
              variant="review"
              label="Near Capacity"
              size="sm"
              icon={AlertTriangle}
            />
          ) : (
            <StatusChip
              variant="verified"
              label="Compliant"
              size="sm"
              icon={CheckCircle2}
            />
          )}
        </div>
      </div>

      {/* Progress Bar Container */}
      <div className="relative w-full h-3.5 bg-slate-100 rounded-full overflow-hidden border border-slate-200 mb-2">
        {/* Occupied Segment */}
        <div
          style={{ width: `${occupiedPct}%` }}
          className={`h-full transition-all duration-300 ${
            isExceeded ? 'bg-rose-600' : isAtLimit ? 'bg-amber-500' : 'bg-blue-800'
          }`}
          title={`Confirmed: ${occupied} / ${approved}`}
        />
        {/* Provisional Segment */}
        {provisional > 0 && (
          <div
            style={{ width: `${provisionalPct}%`, left: `${occupiedPct}%` }}
            className="absolute top-0 h-full bg-amber-400/80 transition-all duration-300"
            title={`Provisional: ${provisional}`}
          />
        )}
      </div>

      {/* Details & Counter */}
      {showDetails && (
        <div className="flex flex-wrap items-center justify-between gap-y-1 text-xs text-slate-600 pt-1">
          <div className="flex items-center gap-3">
            <span>
              Approved: <strong className="text-slate-900 font-semibold">{approved}</strong>
            </span>
            <span>•</span>
            <span>
              Confirmed: <strong className="text-slate-900 font-semibold">{occupied}</strong>
            </span>
            {provisional > 0 && (
              <>
                <span>•</span>
                <span>
                  Provisional: <strong className="text-amber-800 font-semibold">{provisional}</strong>
                </span>
              </>
            )}
            <span>•</span>
            <span>
              {isExceeded ? (
                <span className="text-rose-700 font-bold">Overage: +{overage}</span>
              ) : (
                <span>Remaining: <strong className="text-emerald-800 font-semibold">{remaining}</strong></span>
              )}
            </span>
          </div>

          <div className="text-[11px] text-slate-500 italic">
            {isSupernumerary
              ? 'Rule 3: Isolated quota (never displaces regular intake)'
              : 'Rule 3: Strict statutory approval ceiling'}
          </div>
        </div>
      )}
    </div>
  );
};

export default SeatBar;
