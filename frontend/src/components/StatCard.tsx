import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  colorScheme?: 'blue' | 'emerald' | 'amber' | 'saffron' | 'indigo';
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  colorScheme = 'blue',
}) => {
  const schemeClasses = {
    blue: 'bg-blue-50 text-blue-700 border-blue-100',
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    amber: 'bg-amber-50 text-amber-700 border-amber-100',
    saffron: 'bg-orange-50 text-orange-700 border-orange-100',
    indigo: 'bg-indigo-50 text-indigo-700 border-indigo-100',
  };

  const iconBgClasses = {
    blue: 'bg-blue-600 text-white',
    emerald: 'bg-emerald-600 text-white',
    amber: 'bg-amber-600 text-white',
    saffron: 'bg-orange-600 text-white',
    indigo: 'bg-indigo-600 text-white',
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-lg ${iconBgClasses[colorScheme]}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  );
};
