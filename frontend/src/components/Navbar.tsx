import React from 'react';
import {
  Shield,
  Building2,
  Users,
  CheckCircle,
  FileSearch,
  ScanLine,
  Lock,
  ChevronDown,
  Sparkles,
} from 'lucide-react';
import { SystemRole, UserContext } from '../types';

interface NavbarProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
  userContext: UserContext;
  onRoleChange: (role: SystemRole) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  currentTab,
  onTabChange,
  userContext,
  onRoleChange,
}) => {
  const roles: { role: SystemRole; label: string; desc: string }[] = [
    { role: 'AICTE_ADMIN', label: 'AICTE Admin', desc: 'System-wide compliance & rule versioning' },
    { role: 'AICTE_REVIEWER', label: 'AICTE Reviewer', desc: 'Human adjudication of exception queue' },
    { role: 'INSTITUTION_ADMIN', label: 'Institution Admin', desc: 'COEP Technological Univ scope' },
    { role: 'INSTITUTION_OPERATOR', label: 'Institution Operator', desc: 'Batch admission uploading & verification' },
    { role: 'STUDENT', label: 'Student', desc: 'View admission status & QR credential' },
    { role: 'VERIFIER', label: 'Public Verifier', desc: 'Public cryptographic QR verification' },
    { role: 'AUDITOR', label: 'Auditor', desc: 'Read-only access to immutable audit log' },
  ];

  const tabs = [
    { id: 'overview', label: 'National Command', icon: Building2 },
    { id: 'institution', label: 'Institution Hub', icon: Users },
    { id: 'reviews', label: 'Review Queue', icon: FileSearch },
    { id: 'student', label: 'Student Portal', icon: CheckCircle },
    { id: 'verifier', label: 'Public Verifier', icon: ScanLine },
    { id: 'audit', label: 'Audit Trail', icon: Lock },
  ];

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-40 shadow-xs">
      {/* Top Bar with Ministry Branding & Role Switcher */}
      <div className="bg-slate-900 text-white px-4 py-2 border-b border-slate-800">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-2">
          {/* Brand */}
          <div className="flex items-center space-x-3">
            <div className="bg-orange-600 p-1.5 rounded-lg shadow-sm">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-extrabold text-sm tracking-wider uppercase text-slate-100">
                  AICTE • APAAR Connect
                </span>
                <span className="bg-blue-600/60 text-blue-200 text-[10px] px-2 py-0.5 rounded-full font-semibold border border-blue-400/30">
                  Prototype
                </span>
              </div>
              <p className="text-[10px] text-slate-400">
                All India Council for Technical Education • Ministry of Education
              </p>
            </div>
          </div>

          {/* Interactive Role Switcher */}
          <div className="flex items-center space-x-2 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700">
            <span className="text-[11px] font-medium text-slate-300 flex items-center space-x-1">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>Role Switcher (Rule 7):</span>
            </span>
            <div className="relative inline-block">
              <select
                value={userContext.role}
                onChange={(e) => onRoleChange(e.target.value as SystemRole)}
                className="bg-slate-900 text-amber-300 text-xs font-semibold rounded-lg px-2.5 py-1 border border-slate-600 focus:outline-hidden focus:ring-1 focus:ring-amber-400 cursor-pointer appearance-none pr-7"
              >
                {roles.map((r) => (
                  <option key={r.role} value={r.role} className="bg-slate-900 text-white py-1">
                    {r.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2 top-2 pointer-events-none" />
            </div>
            <span className="text-[10px] text-slate-400 hidden lg:inline">
              ({userContext.institutionId || 'Global Scope'})
            </span>
          </div>
        </div>
      </div>

      {/* Main Navigation Tabs */}
      <div className="max-w-7xl mx-auto px-4">
        <nav className="flex space-x-1 overflow-x-auto py-2">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = currentTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                  active
                    ? 'bg-blue-900 text-white shadow-xs'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                <Icon className={`w-4 h-4 ${active ? 'text-blue-300' : 'text-slate-400'}`} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
};
