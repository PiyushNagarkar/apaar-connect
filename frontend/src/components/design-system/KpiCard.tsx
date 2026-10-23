import React from 'react';
import { ArrowUpRight, ArrowDownRight, Minus, LucideIcon } from 'lucide-react';
import { KpiTrend, StatusVariant } from '../../types';
import { StatusChip } from './StatusChip';

export interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: KpiTrend;
  icon?: LucideIcon;
  badge?: {
    text: string;
    variant?: StatusVariant;
  };
  accentColor?: 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  active?: boolean;
  isLoading?: boolean;
  onClick?: () => void;
  className?: string;
  tooltip?: string;
}

const ACCENT_STYLES = {
  primary: {
    border: 'border-l-4 border-l-blue-900',
    iconBg: 'bg-blue-50 text-blue-900',
    activeBg: 'ring-2 ring-blue-800 bg-blue-50/40',
  },
  success: {
    border: 'border-l-4 border-l-emerald-600',
    iconBg: 'bg-emerald-50 text-emerald-800',
    activeBg: 'ring-2 ring-emerald-600 bg-emerald-50/40',
  },
  warning: {
    border: 'border-l-4 border-l-amber-600',
    iconBg: 'bg-amber-50 text-amber-800',
    activeBg: 'ring-2 ring-amber-600 bg-amber-50/40',
  },
  danger: {
    border: 'border-l-4 border-l-rose-600',
    iconBg: 'bg-rose-50 text-rose-800',
    activeBg: 'ring-2 ring-rose-600 bg-rose-50/40',
  },
  info: {
    border: 'border-l-4 border-l-sky-600',
    iconBg: 'bg-sky-50 text-sky-800',
    activeBg: 'ring-2 ring-sky-600 bg-sky-50/40',
  },
  neutral: {
    border: 'border-l-4 border-l-slate-400',
    iconBg: 'bg-slate-100 text-slate-700',
    activeBg: 'ring-2 ring-slate-400 bg-slate-50',
  },
};

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  subtitle,
  trend,
  icon: Icon,
  badge,
  accentColor = 'primary',
  active = false,
  isLoading = false,
  onClick,
  className = '',
  tooltip,
}) => {
  const isClickable = Boolean(onClick);
  const accent = ACCENT_STYLES[accentColor] || ACCENT_STYLES.primary;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isClickable && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      onClick?.();
    }
  };

  if (isLoading) {
    return (
      <div
        className={`bg-white rounded-lg border border-slate-200 p-5 shadow-xs animate-pulse ${accent.border} ${className}`}
        aria-busy="true"
        aria-label="Loading metric"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="h-4 bg-slate-200 rounded w-2/3" />
          <div className="w-8 h-8 bg-slate-200 rounded-lg" />
        </div>
        <div className="h-8 bg-slate-200 rounded w-1/2 mb-2" />
        <div className="h-3 bg-slate-100 rounded w-3/4" />
      </div>
    );
  }

  return (
    <div
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      title={tooltip}
      className={`group relative bg-white rounded-lg border border-slate-200 p-5 shadow-xs transition-all duration-150 select-none ${
        accent.border
      } ${
        isClickable
          ? 'cursor-pointer hover:shadow-md hover:border-slate-300 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-800 focus-visible:ring-offset-2'
          : ''
      } ${active ? accent.activeBg : ''} ${className}`}
      aria-pressed={isClickable ? active : undefined}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-xs sm:text-sm font-semibold text-slate-700 tracking-tight leading-tight line-clamp-1">
          {title}
        </h3>
        {Icon && (
          <div className={`p-2 rounded-lg shrink-0 ${accent.iconBg}`}>
            <Icon className="w-4 h-4" aria-hidden="true" />
          </div>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="text-2xl sm:text-3xl font-extrabold text-slate-950 font-sans tracking-tight">
          {value}
        </span>
        {badge && (
          <StatusChip
            variant={badge.variant || 'info'}
            label={badge.text}
            size="sm"
            className="shrink-0"
          />
        )}
      </div>

      {(subtitle || trend) && (
        <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-slate-100 text-xs">
          {trend && (
            <span
              className={`inline-flex items-center gap-0.5 font-bold ${
                trend.direction === 'up'
                  ? 'text-emerald-700'
                  : trend.direction === 'down'
                  ? 'text-rose-700'
                  : 'text-slate-600'
              }`}
            >
              {trend.direction === 'up' && <ArrowUpRight className="w-3.5 h-3.5" />}
              {trend.direction === 'down' && <ArrowDownRight className="w-3.5 h-3.5" />}
              {trend.direction === 'neutral' && <Minus className="w-3.5 h-3.5" />}
              {trend.percentage !== undefined && `${trend.percentage}%`}
              {trend.label && <span className="ml-1 font-normal text-slate-500">{trend.label}</span>}
            </span>
          )}
          {subtitle && (
            <span className="text-slate-500 font-normal line-clamp-1 truncate">{subtitle}</span>
          )}
        </div>
      )}

      {isClickable && (
        <span className="sr-only">Click to filter table by {title}</span>
      )}
    </div>
  );
};

export default KpiCard;
