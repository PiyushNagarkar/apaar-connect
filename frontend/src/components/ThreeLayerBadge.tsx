import React from 'react';
import { CheckCircle2, XCircle, AlertCircle, Clock } from 'lucide-react';

interface ThreeLayerBadgeProps {
  l1Status: string;
  l2Status: string;
  l3Status: string;
  size?: 'sm' | 'md';
}

export const ThreeLayerBadge: React.FC<ThreeLayerBadgeProps> = ({
  l1Status,
  l2Status,
  l3Status,
  size = 'md',
}) => {
  const getBadge = (layer: string, status: string, label: string) => {
    const s = (status || '').toUpperCase();
    let bg = 'bg-slate-100 text-slate-700 border-slate-200';
    let Icon = Clock;

    if (s === 'PASS') {
      bg = 'bg-emerald-50 text-emerald-800 border-emerald-200';
      Icon = CheckCircle2;
    } else if (s === 'FAIL') {
      bg = 'bg-rose-50 text-rose-800 border-rose-200';
      Icon = XCircle;
    } else if (s === 'UNAVAILABLE') {
      bg = 'bg-amber-50 text-amber-800 border-amber-300';
      Icon = AlertCircle;
    }

    const padding = size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs';

    return (
      <span
        key={layer}
        className={`inline-flex items-center space-x-1 font-medium rounded border ${bg} ${padding}`}
        title={`${layer}: ${status}`}
      >
        <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
        <span>{label}</span>
      </span>
    );
  };

  return (
    <div className="flex items-center space-x-1.5">
      {getBadge('L1', l1Status, 'L1 (MOCK)')}
      {getBadge('L2', l2Status, 'L2 (Auth)')}
      {getBadge('L3', l3Status, 'L3 (Seats)')}
    </div>
  );
};
