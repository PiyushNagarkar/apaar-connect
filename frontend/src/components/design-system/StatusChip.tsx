import React from 'react';
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Info,
  ShieldCheck,
  ShieldAlert,
  Ban,
  LucideIcon,
} from 'lucide-react';
import { StatusVariant } from '../../types';

export interface StatusChipProps {
  status?: string;
  variant?: StatusVariant;
  label?: string;
  sublabel?: string;
  size?: 'sm' | 'md' | 'lg';
  icon?: LucideIcon;
  className?: string;
}

export function resolveStatusVariant(statusStr: string): {
  variant: StatusVariant;
  label: string;
  defaultIcon: LucideIcon;
} {
  const norm = (statusStr || '').toUpperCase().trim();

  // Green / Verified / Approved / Active
  if (
    [
      'CONFIRMED',
      'ACTIVE',
      'VERIFIED',
      'PASS',
      'PASSED',
      'COMPLIANT',
      'RESOLVED',
      'VALID',
      'GRANTED',
      'ACCEPTED',
      'MATCHED',
    ].includes(norm)
  ) {
    return {
      variant: 'verified',
      label: norm === 'PASS' ? 'Passed' : norm.replace(/_/g, ' '),
      defaultIcon: CheckCircle2,
    };
  }

  // Amber / Under Review / Pending / Warning
  if (
    [
      'UNDER_REVIEW',
      'PENDING',
      'IN_REVIEW',
      'OPEN',
      'AT_LIMIT',
      'NEAR_LIMIT',
      'WARNING',
      'FLAGGED',
      'HIGH_PRIORITY',
      'FUZZY_MATCH',
    ].includes(norm)
  ) {
    return {
      variant: 'review',
      label: norm.replace(/_/g, ' '),
      defaultIcon: Clock,
    };
  }

  // Red / Critical / Breach / Rejected / Exceeded / Revoked
  if (
    [
      'REJECTED',
      'FAIL',
      'FAILED',
      'CRITICAL',
      'BREACH',
      'EXCEEDED',
      'OVERFLOW',
      'REVOKED',
      'CANCELLED',
      'WITHDRAWN',
      'SUSPENDED',
      'ANOMALY',
    ].includes(norm)
  ) {
    return {
      variant: 'critical',
      label: norm === 'FAIL' ? 'Failed' : norm.replace(/_/g, ' '),
      defaultIcon: XCircle,
    };
  }

  // Grey / Unavailable / Not Checked / Skipped
  if (
    [
      'UNAVAILABLE',
      'NOT_CHECKED',
      'NOT_PROVIDED',
      'SKIPPED',
      'NOT_REQUIRED',
      'UNKNOWN',
      'DRAFT',
      'ARCHIVED',
    ].includes(norm)
  ) {
    return {
      variant: 'unavailable',
      label: norm === 'UNAVAILABLE' ? 'Service Unavailable' : norm.replace(/_/g, ' '),
      defaultIcon: HelpCircle,
    };
  }

  // Blue / Info / Provisional / Submitted
  return {
    variant: 'info',
    label: norm ? norm.replace(/_/g, ' ') : 'Info',
    defaultIcon: Info,
  };
}

const VARIANT_STYLES: Record<
  StatusVariant,
  {
    container: string;
    iconColor: string;
    text: string;
    defaultIcon: LucideIcon;
  }
> = {
  verified: {
    container: 'bg-emerald-50 text-emerald-900 border-emerald-300 shadow-sm',
    iconColor: 'text-emerald-700',
    text: 'text-emerald-950',
    defaultIcon: CheckCircle2,
  },
  review: {
    container: 'bg-amber-50 text-amber-900 border-amber-300 shadow-sm',
    iconColor: 'text-amber-700',
    text: 'text-amber-950',
    defaultIcon: AlertTriangle,
  },
  critical: {
    container: 'bg-rose-50 text-rose-900 border-rose-300 shadow-sm',
    iconColor: 'text-rose-700',
    text: 'text-rose-950',
    defaultIcon: ShieldAlert,
  },
  unavailable: {
    container: 'bg-slate-100 text-slate-800 border-slate-300 shadow-sm',
    iconColor: 'text-slate-600',
    text: 'text-slate-900',
    defaultIcon: HelpCircle,
  },
  info: {
    container: 'bg-sky-50 text-sky-900 border-sky-300 shadow-sm',
    iconColor: 'text-sky-700',
    text: 'text-sky-950',
    defaultIcon: Info,
  },
};

const SIZE_STYLES = {
  sm: {
    badge: 'px-2 py-0.5 text-xs gap-1.5 font-medium',
    icon: 'w-3.5 h-3.5 shrink-0',
  },
  md: {
    badge: 'px-2.5 py-1 text-xs sm:text-sm gap-2 font-semibold',
    icon: 'w-4 h-4 shrink-0',
  },
  lg: {
    badge: 'px-3 py-1.5 text-sm sm:text-base gap-2 font-semibold',
    icon: 'w-5 h-5 shrink-0',
  },
};

export const StatusChip: React.FC<StatusChipProps> = ({
  status,
  variant: explicitVariant,
  label: explicitLabel,
  sublabel,
  size = 'md',
  icon: CustomIcon,
  className = '',
}) => {
  const resolved = status ? resolveStatusVariant(status) : null;
  const variant = explicitVariant || (resolved ? resolved.variant : 'info');
  const label = explicitLabel || (resolved ? resolved.label : 'Status');

  const config = VARIANT_STYLES[variant];
  const sizeConfig = SIZE_STYLES[size];
  const IconComponent = CustomIcon || (resolved ? resolved.defaultIcon : config.defaultIcon);

  return (
    <span
      className={`inline-flex items-center rounded-md border transition-colors select-none ${config.container} ${sizeConfig.badge} ${className}`}
      role="status"
      aria-label={`${variant} status: ${label}`}
    >
      <IconComponent className={`${sizeConfig.icon} ${config.iconColor}`} aria-hidden="true" />
      <span className={`tracking-tight capitalize ${config.text}`}>{label}</span>
      {sublabel && (
        <span className="text-[10px] text-slate-500 font-normal border-l border-slate-300 pl-1.5 ml-0.5">
          {sublabel}
        </span>
      )}
    </span>
  );
};

export default StatusChip;
