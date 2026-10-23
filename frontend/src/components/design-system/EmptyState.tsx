import React from 'react';
import { Inbox, LucideIcon } from 'lucide-react';

export interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'No records found',
  description = 'There are no items matching the selected filters or criteria.',
  icon: Icon = Inbox,
  action,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-8 sm:p-12 text-center bg-white rounded-lg border border-dashed border-slate-300 ${className}`}
      role="region"
      aria-label="Empty State"
    >
      <div className="p-3 mb-4 rounded-full bg-slate-100 text-slate-500">
        <Icon className="w-8 h-8" aria-hidden="true" />
      </div>
      <h3 className="text-sm sm:text-base font-bold text-slate-900 mb-1">{title}</h3>
      <p className="text-xs sm:text-sm text-slate-500 max-w-md mb-6">{description}</p>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-900 hover:bg-blue-950 text-white text-xs sm:text-sm font-semibold rounded-md shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2"
        >
          {action.label}
        </button>
      )}
    </div>
  );
};

export default EmptyState;
