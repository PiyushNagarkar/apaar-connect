import React, { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  AlertTriangle,
  Fingerprint,
  Building2,
  Scale,
  ChevronDown,
  Info,
} from 'lucide-react';
import { LayerOutcome } from '../../types';

export interface LayerVerificationState {
  status: LayerOutcome | string;
  confidence?: number;
  reason?: string;
  code?: string;
  timestamp?: string;
}

export interface LayerBadgeProps {
  l1: LayerVerificationState | LayerOutcome | string;
  l2: LayerVerificationState | LayerOutcome | string;
  l3: LayerVerificationState | LayerOutcome | string;
  mode?: 'compact' | 'expanded' | 'interactive';
  className?: string;
}

function normalizeState(
  input: LayerVerificationState | LayerOutcome | string,
): LayerVerificationState {
  if (typeof input === 'string') {
    const norm = input.toUpperCase().trim();
    if (norm === 'PASS' || norm === 'PASSED') return { status: 'PASS' };
    if (norm === 'FAIL' || norm === 'FAILED') return { status: 'FAIL' };
    if (norm === 'UNAVAILABLE' || norm === 'SERVICE_UNAVAILABLE') return { status: 'UNAVAILABLE' };
    if (norm === 'WARNING' || norm === 'WARN') return { status: 'WARNING' };
    return { status: 'SKIPPED' };
  }
  return {
    ...input,
    status: (input.status || 'SKIPPED').toUpperCase().trim() as LayerOutcome,
  };
}

const LAYER_CONFIG = {
  l1: {
    key: 'L1',
    name: 'Identity',
    fullName: 'L1: APAAR / Aadhaar Identity Authentication',
    icon: Fingerprint,
    description: 'Cryptographic biometric & demographic validation against simulated APAAR directory',
  },
  l2: {
    key: 'L2',
    name: 'Authority',
    fullName: 'L2: Statutory Institutional Approval & Intake',
    icon: Building2,
    description: 'AICTE freeze snapshot verification against approved program matrix',
  },
  l3: {
    key: 'L3',
    name: 'Compliance',
    fullName: 'L3: Quota Isolation & Cross-Institution De-duplication',
    icon: Scale,
    description: 'National duplicate detection & strict category quota isolation enforcement',
  },
};

function getOutcomeStyle(status: string) {
  switch (status) {
    case 'PASS':
    case 'PASSED':
      return {
        bg: 'bg-emerald-50 text-emerald-900 border-emerald-300',
        iconColor: 'text-emerald-700',
        icon: CheckCircle2,
        label: 'Passed',
        dot: 'bg-emerald-600',
      };
    case 'FAIL':
    case 'FAILED':
      return {
        bg: 'bg-rose-50 text-rose-900 border-rose-300',
        iconColor: 'text-rose-700',
        icon: XCircle,
        label: 'Failed',
        dot: 'bg-rose-600',
      };
    case 'UNAVAILABLE':
    case 'SERVICE_UNAVAILABLE':
      return {
        bg: 'bg-slate-100 text-slate-800 border-slate-300',
        iconColor: 'text-slate-600',
        icon: HelpCircle,
        label: 'Unavailable',
        dot: 'bg-slate-500',
      };
    case 'WARNING':
    case 'WARN':
      return {
        bg: 'bg-amber-50 text-amber-900 border-amber-300',
        iconColor: 'text-amber-700',
        icon: AlertTriangle,
        label: 'Review',
        dot: 'bg-amber-600',
      };
    default:
      return {
        bg: 'bg-slate-50 text-slate-600 border-slate-200',
        iconColor: 'text-slate-400',
        icon: Info,
        label: 'Skipped',
        dot: 'bg-slate-400',
      };
  }
}

export const LayerBadge: React.FC<LayerBadgeProps> = ({
  l1: rawL1,
  l2: rawL2,
  l3: rawL3,
  mode = 'compact',
  className = '',
}) => {
  const [isExpanded, setIsExpanded] = useState(mode === 'expanded');

  const l1State = normalizeState(rawL1);
  const l2State = normalizeState(rawL2);
  const l3State = normalizeState(rawL3);

  const l1Style = getOutcomeStyle(l1State.status);
  const l2Style = getOutcomeStyle(l2State.status);
  const l3Style = getOutcomeStyle(l3State.status);

  const L1Icon = l1Style.icon;
  const L2Icon = l2Style.icon;
  const L3Icon = l3Style.icon;

  if (mode === 'compact') {
    return (
      <div
        className={`inline-flex items-center gap-1.5 p-1 bg-white border border-slate-200 rounded-lg shadow-xs ${className}`}
        role="group"
        aria-label="3-Layer Verification Status"
      >
        {/* L1 Identity */}
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l1Style.bg}`}
          title={`${LAYER_CONFIG.l1.fullName}: ${l1Style.label} ${l1State.reason ? `(${l1State.reason})` : ''}`}
        >
          <L1Icon className={`w-3.5 h-3.5 ${l1Style.iconColor}`} aria-hidden="true" />
          <span>L1: {l1Style.label}</span>
        </span>

        {/* L2 Authority */}
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l2Style.bg}`}
          title={`${LAYER_CONFIG.l2.fullName}: ${l2Style.label} ${l2State.reason ? `(${l2State.reason})` : ''}`}
        >
          <L2Icon className={`w-3.5 h-3.5 ${l2Style.iconColor}`} aria-hidden="true" />
          <span>L2: {l2Style.label}</span>
        </span>

        {/* L3 Compliance */}
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l3Style.bg}`}
          title={`${LAYER_CONFIG.l3.fullName}: ${l3Style.label} ${l3State.reason ? `(${l3State.reason})` : ''}`}
        >
          <L3Icon className={`w-3.5 h-3.5 ${l3Style.iconColor}`} aria-hidden="true" />
          <span>L3: {l3Style.label}</span>
        </span>
      </div>
    );
  }

  return (
    <div className={`bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden ${className}`}>
      {mode === 'interactive' && (
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-between px-3 py-2 bg-slate-50 hover:bg-slate-100 transition-colors border-b border-slate-200 text-left"
        >
          <span className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
            3-Layer Technical Verification
          </span>
          <ChevronDown
            className={`w-4 h-4 text-slate-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          />
        </button>
      )}

      {(isExpanded || mode === 'expanded') && (
        <div className="divide-y divide-slate-100 p-3 space-y-3">
          {/* L1 */}
          <div className="flex items-start justify-between gap-3 pt-1">
            <div className="flex items-start gap-2.5">
              <LAYER_CONFIG.l1.icon className="w-4 h-4 text-blue-700 mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-bold text-slate-900">{LAYER_CONFIG.l1.fullName}</p>
                <p className="text-[11px] text-slate-500">{LAYER_CONFIG.l1.description}</p>
                {l1State.reason && (
                  <p className="text-[11px] text-slate-600 mt-0.5 font-mono bg-slate-50 px-1.5 py-0.5 rounded border border-slate-200 inline-block">
                    {l1State.reason}
                  </p>
                )}
              </div>
            </div>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l1Style.bg}`}>
              <L1Icon className={`w-3.5 h-3.5 ${l1Style.iconColor}`} />
              {l1Style.label}
            </span>
          </div>

          {/* L2 */}
          <div className="flex items-start justify-between gap-3 pt-3">
            <div className="flex items-start gap-2.5">
              <LAYER_CONFIG.l2.icon className="w-4 h-4 text-indigo-700 mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-bold text-slate-900">{LAYER_CONFIG.l2.fullName}</p>
                <p className="text-[11px] text-slate-500">{LAYER_CONFIG.l2.description}</p>
                {l2State.reason && (
                  <p className="text-[11px] text-slate-600 mt-0.5 font-mono bg-slate-50 px-1.5 py-0.5 rounded border border-slate-200 inline-block">
                    {l2State.reason}
                  </p>
                )}
              </div>
            </div>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l2Style.bg}`}>
              <L2Icon className={`w-3.5 h-3.5 ${l2Style.iconColor}`} />
              {l2Style.label}
            </span>
          </div>

          {/* L3 */}
          <div className="flex items-start justify-between gap-3 pt-3">
            <div className="flex items-start gap-2.5">
              <LAYER_CONFIG.l3.icon className="w-4 h-4 text-purple-700 mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-bold text-slate-900">{LAYER_CONFIG.l3.fullName}</p>
                <p className="text-[11px] text-slate-500">{LAYER_CONFIG.l3.description}</p>
                {l3State.reason && (
                  <p className="text-[11px] text-slate-600 mt-0.5 font-mono bg-slate-50 px-1.5 py-0.5 rounded border border-slate-200 inline-block">
                    {l3State.reason}
                  </p>
                )}
              </div>
            </div>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${l3Style.bg}`}>
              <L3Icon className={`w-3.5 h-3.5 ${l3Style.iconColor}`} />
              {l3Style.label}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default LayerBadge;
