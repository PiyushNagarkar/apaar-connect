import React from 'react';
import { AlertCircle, ShieldAlert } from 'lucide-react';

export const FooterBanner: React.FC = () => {
  return (
    <footer className="w-full bg-slate-900 border-t border-slate-800 text-slate-300 py-3 px-4 text-xs">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
          <span className="font-semibold text-amber-300 tracking-wide uppercase">
            Mandatory Disclaimer (Rule 2):
          </span>
          <span className="text-slate-200">
            Synthetic data. Simulated APAAR service.
          </span>
        </div>
        <div className="flex items-center space-x-4 text-slate-400">
          <span>Identity Adapter: <strong className="text-blue-400">MOCK_APAAR_V1</strong></span>
          <span>•</span>
          <span>AICTE Hackathon Prototype (48hr Modular Monolith)</span>
        </div>
      </div>
    </footer>
  );
};
