import React from 'react';

export interface SkeletonProps {
  className?: string;
  count?: number;
}

export const SkeletonText: React.FC<{
  className?: string;
  lines?: number;
  width?: string;
}> = ({ className = '', lines = 1, width = 'w-full' }) => {
  if (lines === 1) {
    return (
      <div
        className={`h-4 bg-slate-200 rounded animate-pulse ${width} ${className}`}
        aria-hidden="true"
      />
    );
  }

  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`h-4 bg-slate-200 rounded animate-pulse ${
            i === lines - 1 ? 'w-2/3' : 'w-full'
          }`}
        />
      ))}
    </div>
  );
};

export const SkeletonBadge: React.FC<{ className?: string }> = ({ className = '' }) => {
  return (
    <div
      className={`h-6 w-20 bg-slate-200 rounded-md animate-pulse ${className}`}
      aria-hidden="true"
    />
  );
};

export const SkeletonCard: React.FC<{ className?: string }> = ({ className = '' }) => {
  return (
    <div
      className={`bg-white rounded-lg border border-slate-200 p-5 shadow-xs animate-pulse ${className}`}
      aria-hidden="true"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="h-4 bg-slate-200 rounded w-1/2" />
        <div className="w-8 h-8 bg-slate-100 rounded-lg" />
      </div>
      <div className="h-8 bg-slate-200 rounded w-2/3 mb-2" />
      <div className="h-3 bg-slate-100 rounded w-3/4" />
    </div>
  );
};

export const SkeletonTable: React.FC<{
  rows?: number;
  cols?: number;
  className?: string;
}> = ({ rows = 5, cols = 4, className = '' }) => {
  return (
    <div
      className={`bg-white rounded-lg border border-slate-200 overflow-hidden shadow-xs animate-pulse ${className}`}
      aria-hidden="true"
    >
      {/* Header skeleton */}
      <div className="bg-slate-100 px-4 py-3 border-b border-slate-200 flex gap-4">
        {Array.from({ length: cols }).map((_, c) => (
          <div key={c} className="h-4 bg-slate-200 rounded flex-1" />
        ))}
      </div>
      {/* Rows skeleton */}
      <div className="divide-y divide-slate-100">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="px-4 py-3 flex gap-4 items-center">
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className={`h-4 bg-slate-100 rounded flex-1 ${
                  c === 0 ? 'w-1/3' : 'w-full'
                }`}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
};

export default {
  Text: SkeletonText,
  Badge: SkeletonBadge,
  Card: SkeletonCard,
  Table: SkeletonTable,
};
