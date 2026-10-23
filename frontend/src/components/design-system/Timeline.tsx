import React from 'react';
import {
  Calendar,
  User,
  Clock,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { TimelineEvent } from '../../types';
import { StatusChip } from './StatusChip';

export interface TimelineProps {
  events: TimelineEvent[];
  compact?: boolean;
  className?: string;
}

export const Timeline: React.FC<TimelineProps> = ({
  events,
  compact = false,
  className = '',
}) => {
  if (!events || events.length === 0) {
    return (
      <div className="p-4 text-center text-xs text-slate-500 italic bg-slate-50 rounded-lg border border-slate-200">
        No chronological audit trail events recorded yet.
      </div>
    );
  }

  return (
    <div className={`relative pl-4 sm:pl-6 space-y-6 ${className}`}>
      {/* Vertical continuous timeline bar */}
      <div className="absolute left-[11px] sm:left-[19px] top-2 bottom-2 w-0.5 bg-slate-200 pointer-events-none" />

      {events.map((evt, idx) => {
        const variant = evt.statusVariant || 'info';

        return (
          <div key={evt.id || idx} className="relative flex items-start gap-3 sm:gap-4 group">
            {/* Timeline node marker */}
            <div
              className={`relative z-10 w-4 h-4 sm:w-5 sm:h-5 rounded-full border-2 bg-white flex items-center justify-center shrink-0 mt-1 transition-transform group-hover:scale-110 ${
                variant === 'verified'
                  ? 'border-emerald-600 ring-2 ring-emerald-100'
                  : variant === 'critical'
                  ? 'border-rose-600 ring-2 ring-rose-100'
                  : variant === 'review'
                  ? 'border-amber-500 ring-2 ring-amber-100'
                  : 'border-blue-700 ring-2 ring-blue-100'
              }`}
            >
              <div
                className={`w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full ${
                  variant === 'verified'
                    ? 'bg-emerald-600'
                    : variant === 'critical'
                    ? 'bg-rose-600'
                    : variant === 'review'
                    ? 'bg-amber-500'
                    : 'bg-blue-700'
                }`}
              />
            </div>

            {/* Event content box */}
            <div className="flex-1 bg-white border border-slate-200 rounded-lg p-3 sm:p-4 shadow-2xs hover:border-slate-300 transition-colors">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <h4 className="text-xs sm:text-sm font-bold text-slate-900 tracking-tight">
                    {evt.title}
                  </h4>
                  {evt.statusLabel && (
                    <StatusChip
                      variant={evt.statusVariant || 'info'}
                      label={evt.statusLabel}
                      size="sm"
                    />
                  )}
                </div>

                <div className="flex items-center gap-1.5 text-[11px] text-slate-500 font-mono">
                  <Clock className="w-3.5 h-3.5 text-slate-400" />
                  <span>{evt.timestamp}</span>
                </div>
              </div>

              {evt.description && (
                <p className="text-xs text-slate-600 mb-2 leading-relaxed">
                  {evt.description}
                </p>
              )}

              {(evt.actor || evt.role) && (
                <div className="flex items-center gap-3 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
                  {evt.actor && (
                    <span className="flex items-center gap-1">
                      <User className="w-3.5 h-3.5 text-slate-400" />
                      <strong className="text-slate-700 font-semibold">{evt.actor}</strong>
                    </span>
                  )}
                  {evt.role && (
                    <span className="bg-slate-100 px-1.5 py-0.5 rounded text-[10px] font-medium text-slate-600">
                      {evt.role}
                    </span>
                  )}
                </div>
              )}

              {evt.details && Object.keys(evt.details).length > 0 && !compact && (
                <div className="mt-2.5 p-2 bg-slate-50 rounded border border-slate-200 font-mono text-[11px] text-slate-700 overflow-x-auto">
                  <div className="font-semibold text-slate-500 text-[10px] uppercase mb-1">
                    Event Metadata
                  </div>
                  <pre className="whitespace-pre-wrap">{JSON.stringify(evt.details, null, 2)}</pre>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default Timeline;
