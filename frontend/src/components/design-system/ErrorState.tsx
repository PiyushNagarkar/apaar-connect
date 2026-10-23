import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export interface ErrorStateProps {
  title?: string;
  message?: string;
  code?: string | number;
  requestId?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Unable to Load Data',
  message = 'An unexpected error occurred while communicating with the server. Please verify your connection or retry.',
  code,
  requestId,
  onRetry,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-8 sm:p-12 text-center bg-rose-50/40 rounded-lg border border-rose-200 ${className}`}
      role="alert"
      aria-live="assertive"
    >
      <div className="p-3 mb-4 rounded-full bg-rose-100 text-rose-700">
        <AlertTriangle className="w-8 h-8" aria-hidden="true" />
      </div>
      <h3 className="text-sm sm:text-base font-bold text-rose-950 mb-1">{title}</h3>
      <p className="text-xs sm:text-sm text-rose-800 max-w-md mb-4">{message}</p>

      {(code || requestId) && (
        <div className="mb-6 flex flex-wrap items-center justify-center gap-2 text-[11px] text-slate-500 font-mono bg-white px-3 py-1.5 rounded border border-rose-200">
          {code && <span>Code: <strong>{code}</strong></span>}
          {code && requestId && <span>•</span>}
          {requestId && <span>Trace ID: <code className="text-slate-700">{requestId}</code></span>}
        </div>
      )}

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 px-4 py-2 bg-rose-700 hover:bg-rose-800 text-white text-xs sm:text-sm font-semibold rounded-md shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-600 focus-visible:ring-offset-2"
        >
          <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
          <span>Retry Operation</span>
        </button>
      )}
    </div>
  );
};

export default ErrorState;
