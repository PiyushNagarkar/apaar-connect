import React from 'react';
import { ShieldAlert, ShieldCheck, Database } from 'lucide-react';

export interface FooterBannerProps {
  className?: string;
  showDetails?: boolean;
}

export const FooterBanner: React.FC<FooterBannerProps> = ({
  className = '',
  showDetails = true,
}) => {
  return (
    <footer
      className={`w-full bg-[#0a192f] border-t border-slate-800 text-slate-300 py-3 px-4 text-xs select-none ${className}`}
      role="contentinfo"
      aria-label="Statutory Regulatory Sandbox Disclaimer"
    >
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3 text-center md:text-left">
        {/* Core Regulatory Mandatory Disclaimer */}
        <div className="flex flex-wrap items-center justify-center md:justify-start gap-2">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold uppercase tracking-wider text-[11px] border border-amber-500/30">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400 shrink-0" aria-hidden="true" />
            Regulatory Sandbox Notice
          </span>
          <span className="font-semibold text-white tracking-tight">
            Synthetic data. Simulated APAAR service.
          </span>
          <span className="text-slate-400 text-[11px] hidden sm:inline">
            All student identities, enrollment records & verification responses are generated for demonstration.
          </span>
        </div>

        {/* Technical & Compliance Details */}
        {showDetails && (
          <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 text-[11px] text-slate-400 font-mono">
            <span className="flex items-center gap-1 text-slate-300">
              <Database className="w-3.5 h-3.5 text-blue-400" />
              <span>Adapter: <strong>MOCK_APAAR_V1</strong></span>
            </span>
            <span>•</span>
            <span className="flex items-center gap-1 text-slate-300">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Ed25519 & SHA-256 Validated</span>
            </span>
            <span>•</span>
            <span className="text-slate-400">AICTE Act 1987 & DPDP Act 2023 Sandbox</span>
          </div>
        )}
      </div>
    </footer>
  );
};

export default FooterBanner;
