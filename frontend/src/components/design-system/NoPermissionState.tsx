import React from 'react';
import { ShieldAlert, ArrowLeft } from 'lucide-react';
import { SystemRole } from '../../types';

export interface NoPermissionStateProps {
  currentRole?: SystemRole;
  requiredRoles?: SystemRole[];
  onNavigateHome?: () => void;
  className?: string;
}

export const NoPermissionState: React.FC<NoPermissionStateProps> = ({
  currentRole,
  requiredRoles,
  onNavigateHome,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-8 sm:p-12 text-center bg-white rounded-lg border border-slate-300 shadow-xs ${className}`}
      role="alert"
    >
      <div className="p-3 mb-4 rounded-full bg-amber-100 text-amber-800">
        <ShieldAlert className="w-9 h-9" aria-hidden="true" />
      </div>
      <h3 className="text-base sm:text-lg font-bold text-slate-900 mb-1">
        Access Restricted (Statutory Role Scope)
      </h3>
      <p className="text-xs sm:text-sm text-slate-600 max-w-lg mb-4 leading-relaxed">
        Your current session role{' '}
        <strong className="text-slate-900 bg-slate-100 px-1.5 py-0.5 rounded font-mono">
          {currentRole || 'UNKNOWN'}
        </strong>{' '}
        does not have statutory authorization to inspect or execute actions within this section.
        Role boundaries are cryptographically enforced pursuant to AICTE Institutional Compliance
        Rules and DPDP Act 2023.
      </p>

      {requiredRoles && requiredRoles.length > 0 && (
        <div className="mb-6 flex items-center justify-center gap-1.5 text-xs text-slate-500">
          <span>Authorized roles:</span>
          <div className="flex flex-wrap gap-1">
            {requiredRoles.map((r) => (
              <span
                key={r}
                className="bg-slate-100 text-slate-800 px-2 py-0.5 rounded text-[11px] font-mono font-medium border border-slate-200"
              >
                {r}
              </span>
            ))}
          </div>
        </div>
      )}

      {onNavigateHome && (
        <button
          type="button"
          onClick={onNavigateHome}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-900 hover:bg-blue-950 text-white text-xs sm:text-sm font-semibold rounded-md shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Return to Designated Landing Page</span>
        </button>
      )}
    </div>
  );
};

export default NoPermissionState;
