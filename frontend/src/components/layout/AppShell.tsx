import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Building2,
  ListFilter,
  CreditCard,
  QrCode,
  FileCheck2,
  Layers,
  Menu,
  X,
  ChevronDown,
  Shield,
  User,
  GraduationCap,
  Sparkles,
  LogOut,
  ExternalLink,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { SystemRole } from '../../types';
import { FooterBanner } from '../design-system/FooterBanner';
import { StatusChip } from '../design-system/StatusChip';

interface NavItemConfig {
  path: string;
  label: string;
  description: string;
  icon: React.ElementType;
  allowedRoles: SystemRole[];
  badge?: string;
}

const NAVIGATION_ITEMS: NavItemConfig[] = [
  {
    path: '/command-centre',
    label: 'Command Centre',
    description: 'National overview & risk priority monitoring',
    icon: LayoutDashboard,
    allowedRoles: ['AICTE_ADMIN', 'AICTE_REVIEWER', 'AUDITOR'],
  },
  {
    path: '/workspace',
    label: 'Workspace',
    description: 'Institutional seat matrix & enrollment desk',
    icon: Building2,
    allowedRoles: ['INSTITUTION_ADMIN', 'INSTITUTION_OPERATOR', 'AICTE_ADMIN'],
  },
  {
    path: '/reviews',
    label: 'Review Queue',
    description: 'Autonomous discrepancy review & hearings',
    icon: ListFilter,
    allowedRoles: ['AICTE_ADMIN', 'AICTE_REVIEWER', 'INSTITUTION_ADMIN', 'AUDITOR'],
  },
  {
    path: '/student-card',
    label: 'Student Card',
    description: 'Verifiable credentials & consent management',
    icon: CreditCard,
    allowedRoles: ['STUDENT', 'INSTITUTION_ADMIN', 'AICTE_ADMIN', 'VERIFIER'],
  },
  {
    path: '/verify',
    label: 'Public Verifier',
    description: 'Cryptographic offline & QR verification',
    icon: QrCode,
    allowedRoles: ['VERIFIER', 'STUDENT', 'AICTE_ADMIN', 'INSTITUTION_ADMIN', 'AUDITOR'],
  },
  {
    path: '/audit',
    label: 'Audit Trail',
    description: 'Immutable SHA-256 hash-chain verification',
    icon: FileCheck2,
    allowedRoles: ['AUDITOR', 'AICTE_ADMIN'],
  },
  {
    path: '/dev/components',
    label: 'Component Lab',
    description: 'Storybook-like design system showroom',
    icon: Layers,
    allowedRoles: [
      'AICTE_ADMIN',
      'AICTE_REVIEWER',
      'INSTITUTION_ADMIN',
      'INSTITUTION_OPERATOR',
      'STUDENT',
      'VERIFIER',
      'AUDITOR',
    ],
    badge: 'Design System',
  },
];

export const AppShell: React.FC = () => {
  const { user, role, switchRole, roleMeta, getLandingPath } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [roleDropdownOpen, setRoleDropdownOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const handleRoleSwitch = (newRole: SystemRole) => {
    switchRole(newRole);
    setRoleDropdownOpen(false);
    setMobileMenuOpen(false);
    // Automatic role-based landing redirection (Rule requirement)
    const targetPath = getLandingPath(newRole);
    navigate(targetPath);
  };

  const visibleNavItems = NAVIGATION_ITEMS.filter((item) =>
    item.allowedRoles.includes(role),
  );

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900 font-sans">
      {/* ---------------- Top Bar (Govtech Header) ---------------- */}
      <header className="sticky top-0 z-30 w-full bg-[#0a192f] text-white border-b border-slate-800 shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          {/* Left: Emblem & National Title */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2 text-slate-300 hover:text-white rounded-lg hover:bg-slate-800/80 transition-colors"
              aria-label="Toggle Navigation Menu"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>

            <div
              onClick={() => navigate(getLandingPath())}
              className="flex items-center gap-3 cursor-pointer group"
              title="Go to role dashboard"
            >
              {/* National Emblem Symbol */}
              <div className="w-9 h-9 rounded-lg bg-blue-900/80 border border-blue-700/60 flex items-center justify-center p-1.5 shrink-0 shadow-xs group-hover:border-blue-500 transition-colors">
                <GraduationCap className="w-full h-full text-blue-200" />
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <span className="font-extrabold text-sm sm:text-base tracking-tight text-white">
                    APAAR Connect
                  </span>
                  <span className="hidden sm:inline-block px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 text-[10px] font-bold tracking-wider uppercase border border-amber-500/30">
                    AICTE Sandbox
                  </span>
                </div>
                <p className="text-[10px] text-slate-400 hidden sm:block tracking-wide">
                  Technical Education Regulatory & Capacity Intelligence
                </p>
              </div>
            </div>
          </div>

          {/* Right: Role Switcher & User Profile Pill */}
          <div className="flex items-center gap-3">
            {/* Quick Role Switcher Dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setRoleDropdownOpen(!roleDropdownOpen)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/90 hover:bg-slate-700/90 text-xs text-white border border-slate-700 shadow-2xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                aria-expanded={roleDropdownOpen}
                aria-haspopup="true"
              >
                <Shield className="w-3.5 h-3.5 text-blue-400" />
                <span className="font-semibold hidden sm:inline">Role:</span>
                <span className="font-bold text-blue-300 truncate max-w-[130px]">
                  {roleMeta.badge}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              </button>

              {roleDropdownOpen && (
                <div
                  className="absolute right-0 mt-2 w-72 bg-white rounded-xl shadow-2xl border border-slate-200 py-2 z-50 text-slate-900 animate-in fade-in zoom-in-95 duration-100"
                  role="menu"
                >
                  <div className="px-3 py-2 border-b border-slate-100 bg-slate-50/60 rounded-t-lg">
                    <p className="text-xs font-bold text-slate-800">Simulate Government Role</p>
                    <p className="text-[11px] text-slate-500">
                      Instantly switches view & tests RBAC route guards
                    </p>
                  </div>

                  <div className="max-h-80 overflow-y-auto p-1 divide-y divide-slate-50">
                    {(
                      [
                        'AICTE_ADMIN',
                        'AICTE_REVIEWER',
                        'INSTITUTION_ADMIN',
                        'INSTITUTION_OPERATOR',
                        'STUDENT',
                        'VERIFIER',
                        'AUDITOR',
                      ] as SystemRole[]
                    ).map((r) => {
                      const isCurrent = r === role;
                      return (
                        <button
                          key={r}
                          type="button"
                          onClick={() => handleRoleSwitch(r)}
                          className={`w-full text-left px-3 py-2 rounded-lg text-xs flex flex-col transition-colors ${
                            isCurrent
                              ? 'bg-blue-50 text-blue-900 font-bold border border-blue-200'
                              : 'hover:bg-slate-100 text-slate-700'
                          }`}
                          role="menuitem"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-semibold">{r.replace(/_/g, ' ')}</span>
                            {isCurrent && (
                              <span className="text-[10px] text-blue-800 bg-blue-100 px-1.5 py-0.2 rounded font-bold">
                                Active
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-500 mt-0.5">
                            {r.startsWith('AICTE')
                              ? 'Command Centre & Quotas'
                              : r.startsWith('INST')
                              ? 'College Admissions & Submissions'
                              : r === 'STUDENT'
                              ? 'Learner Identity & Consent'
                              : r === 'AUDITOR'
                              ? 'SHA-256 Audit Surveillance'
                              : 'Third-party Credential Verification'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* Active User Avatar Pill */}
            <div className="hidden lg:flex items-center gap-2.5 pl-3 border-l border-slate-700/80">
              <div className="w-8 h-8 rounded-full bg-blue-800 border border-blue-600 flex items-center justify-center text-xs font-bold text-white shadow-2xs">
                {user.name.charAt(0)}
              </div>
              <div className="text-left text-xs">
                <p className="font-bold text-white line-clamp-1 leading-tight">{user.name}</p>
                <p className="text-[10px] text-slate-400 font-mono">
                  {user.institutionId || 'National HQ'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ---------------- Main Layout (Sidebar + Content Viewport) ---------------- */}
      <div className="flex-1 flex w-full max-w-7xl mx-auto">
        {/* Desktop Sidebar */}
        <aside className="hidden md:flex flex-col w-64 border-r border-slate-200 bg-white py-5 px-3 shrink-0">
          <div className="px-3 mb-3">
            <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">
              Navigation
            </span>
          </div>

          <nav className="flex-1 space-y-1" aria-label="Sidebar Navigation">
            {visibleNavItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `group flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-semibold transition-all ${
                      isActive
                        ? 'bg-blue-900 text-white shadow-xs'
                        : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <div className="flex items-center gap-3">
                        <Icon
                          className={`w-4 h-4 shrink-0 transition-colors ${
                            isActive
                              ? 'text-blue-200'
                              : 'text-slate-500 group-hover:text-slate-800'
                          }`}
                          aria-hidden="true"
                        />
                        <span>{item.label}</span>
                      </div>
                      {item.badge && (
                        <span
                          className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider ${
                            isActive
                              ? 'bg-blue-800 text-blue-100 border border-blue-700'
                              : 'bg-slate-100 text-slate-600 border border-slate-200'
                          }`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Institutional Scope Info Card */}
          <div className="mt-auto pt-4 border-t border-slate-200 px-3">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-xs">
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1">
                Active Authority Scope
              </span>
              <p className="font-bold text-slate-900 truncate">
                {user.institutionId ? user.institutionId : 'National AICTE Apex'}
              </p>
              <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                Role: {roleMeta.badge}
              </p>
            </div>
          </div>
        </aside>

        {/* Mobile Navigation Drawer */}
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-slate-900/60 backdrop-blur-xs md:hidden"
            onClick={() => setMobileMenuOpen(false)}
          >
            <div
              className="fixed inset-y-0 left-0 w-72 bg-white shadow-2xl p-4 flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-4">
                <div className="flex items-center gap-2">
                  <GraduationCap className="w-5 h-5 text-blue-900" />
                  <span className="font-bold text-sm text-slate-900">APAAR Connect</span>
                </div>
                <button
                  type="button"
                  onClick={() => setMobileMenuOpen(false)}
                  className="p-1 rounded text-slate-500 hover:text-slate-800"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <nav className="flex-1 space-y-1">
                {visibleNavItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      onClick={() => setMobileMenuOpen(false)}
                      className={({ isActive }) =>
                        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-semibold ${
                          isActive
                            ? 'bg-blue-900 text-white'
                            : 'text-slate-700 hover:bg-slate-100'
                        }`
                      }
                    >
                      <Icon className="w-4 h-4 shrink-0" />
                      <span>{item.label}</span>
                    </NavLink>
                  );
                })}
              </nav>

              <div className="pt-4 border-t border-slate-200">
                <p className="text-xs text-slate-500 mb-2 font-semibold">Active User Profile</p>
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-xs">
                  <p className="font-bold text-slate-900">{user.name}</p>
                  <p className="text-[11px] text-slate-500">{roleMeta.badge}</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ---------------- Primary Content Viewport ---------------- */}
        <main className="flex-1 w-full min-w-0 px-4 sm:px-6 py-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      {/* ---------------- Persistent Statutory Footer Banner ---------------- */}
      <FooterBanner />
    </div>
  );
};

export default AppShell;
