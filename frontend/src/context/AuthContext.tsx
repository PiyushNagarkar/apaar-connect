import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { SystemRole, UserContext } from '../types';
import { setApiAuthContext } from '../services/api';

export interface AuthContextType {
  user: UserContext;
  role: SystemRole;
  switchRole: (newRole: SystemRole, customInstitutionId?: string) => void;
  getLandingPath: (targetRole?: SystemRole) => string;
  isAllowedRoute: (path: string) => boolean;
  roleMeta: {
    title: string;
    description: string;
    color: string;
    badge: string;
  };
}

const ROLE_METADATA: Record<
  SystemRole,
  { title: string; description: string; color: string; badge: string }
> = {
  AICTE_ADMIN: {
    title: 'AICTE Apex Administrator',
    description: 'National overview, institutional quotas & statutory policy control',
    color: 'bg-indigo-900 text-white',
    badge: 'National Regulator',
  },
  AICTE_REVIEWER: {
    title: 'AICTE Hearing Officer / Reviewer',
    description: 'Autonomous discrepancy adjudication & review queue priority',
    color: 'bg-blue-800 text-white',
    badge: 'Appeals & Review',
  },
  INSTITUTION_ADMIN: {
    title: 'Institution Principal / Dean',
    description: 'Seat compliance oversight, batch submissions & credentials issuance',
    color: 'bg-emerald-800 text-white',
    badge: 'College Leadership',
  },
  INSTITUTION_OPERATOR: {
    title: 'Admission Cell Operator',
    description: 'Daily student enrollment entry, document upload & pre-validation',
    color: 'bg-teal-800 text-white',
    badge: 'Data Entry Desk',
  },
  STUDENT: {
    title: 'Enrolled Student',
    description: 'Verifiable APAAR card, consent management & correction appeals',
    color: 'bg-sky-800 text-white',
    badge: 'Learner Identity',
  },
  VERIFIER: {
    title: 'Third-Party Verifier / Employer',
    description: 'Public cryptographic QR verification & status lookup',
    color: 'bg-slate-800 text-white',
    badge: 'External Verifier',
  },
  AUDITOR: {
    title: 'Independent Compliance Auditor',
    description: 'Cryptographic hash-chain inspection & read access surveillance',
    color: 'bg-purple-900 text-white',
    badge: 'Statutory Audit',
  },
};

const DEFAULT_DEMO_USERS: Record<SystemRole, UserContext> = {
  AICTE_ADMIN: {
    role: 'AICTE_ADMIN',
    userId: 'usr-aicte-adm-01',
    name: 'Dr. Ramesh Sharma (Adviser-1)',
    institutionId: 'INST-IITD',
  },
  AICTE_REVIEWER: {
    role: 'AICTE_REVIEWER',
    userId: 'usr-aicte-rev-01',
    name: 'Prof. Sunita Rao (Hearing Officer)',
    institutionId: 'INST-IITD',
  },
  INSTITUTION_ADMIN: {
    role: 'INSTITUTION_ADMIN',
    userId: 'usr-inst-adm-coep',
    name: 'Dr. Anand Joshi (Director, COEP)',
    institutionId: 'INST-COEP-PUNE',
  },
  INSTITUTION_OPERATOR: {
    role: 'INSTITUTION_OPERATOR',
    userId: 'usr-inst-op-coep',
    name: 'Vikas Patil (Admission Officer)',
    institutionId: 'INST-COEP-PUNE',
  },
  STUDENT: {
    role: 'STUDENT',
    userId: 'usr-stud-pooja-01',
    name: 'Pooja Agarwal (B.Tech CSE)',
    studentId: 'STU-DEMO-001',
    institutionId: 'INST-IITD',
  },
  VERIFIER: {
    role: 'VERIFIER',
    userId: 'usr-verifier-tcs',
    name: 'TCS Background Check Desk',
  },
  AUDITOR: {
    role: 'AUDITOR',
    userId: 'usr-auditor-cag',
    name: 'CAG Technical Education Audit Wing',
  },
};

// Route access rules per role
const ROUTE_PERMISSIONS: Record<string, SystemRole[]> = {
  '/command-centre': ['AICTE_ADMIN', 'AICTE_REVIEWER', 'AUDITOR'],
  '/workspace': ['INSTITUTION_ADMIN', 'INSTITUTION_OPERATOR', 'AICTE_ADMIN'],
  '/reviews': ['AICTE_ADMIN', 'AICTE_REVIEWER', 'INSTITUTION_ADMIN', 'AUDITOR'],
  '/student-card': ['STUDENT', 'INSTITUTION_ADMIN', 'AICTE_ADMIN', 'VERIFIER'],
  '/verify': ['VERIFIER', 'STUDENT', 'AICTE_ADMIN', 'INSTITUTION_ADMIN', 'AUDITOR'],
  '/audit': ['AUDITOR', 'AICTE_ADMIN'],
  '/dev/components': [
    'AICTE_ADMIN',
    'AICTE_REVIEWER',
    'INSTITUTION_ADMIN',
    'INSTITUTION_OPERATOR',
    'STUDENT',
    'VERIFIER',
    'AUDITOR',
  ],
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [role, setRole] = useState<SystemRole>(() => {
    const saved = localStorage.getItem('aicte_demo_role');
    return (saved as SystemRole) || 'AICTE_ADMIN';
  });

  const [user, setUser] = useState<UserContext>(() => {
    return DEFAULT_DEMO_USERS[role];
  });

  const switchRole = (newRole: SystemRole, customInstitutionId?: string) => {
    const baseProfile = DEFAULT_DEMO_USERS[newRole];
    const updatedUser: UserContext = {
      ...baseProfile,
      institutionId: customInstitutionId || baseProfile.institutionId,
    };

    setRole(newRole);
    setUser(updatedUser);
    localStorage.setItem('aicte_demo_role', newRole);
    setApiAuthContext(newRole, updatedUser.institutionId, updatedUser.userId, updatedUser.studentId);
  };

  useEffect(() => {
    setApiAuthContext(role, user.institutionId, user.userId, user.studentId);
  }, [role, user]);

  const getLandingPath = (targetRole: SystemRole = role): string => {
    switch (targetRole) {
      case 'AICTE_ADMIN':
      case 'AICTE_REVIEWER':
        return '/command-centre';
      case 'INSTITUTION_ADMIN':
      case 'INSTITUTION_OPERATOR':
        return '/workspace';
      case 'STUDENT':
        return '/student-card';
      case 'VERIFIER':
        return '/verify';
      case 'AUDITOR':
        return '/audit';
      default:
        return '/command-centre';
    }
  };

  const isAllowedRoute = (path: string): boolean => {
    const exactMatch = ROUTE_PERMISSIONS[path];
    if (exactMatch) {
      return exactMatch.includes(role);
    }
    // Prefix match
    for (const [routePrefix, allowedRoles] of Object.entries(ROUTE_PERMISSIONS)) {
      if (path.startsWith(routePrefix)) {
        return allowedRoles.includes(role);
      }
    }
    return true;
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        role,
        switchRole,
        getLandingPath,
        isAllowedRoute,
        roleMeta: ROLE_METADATA[role],
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
