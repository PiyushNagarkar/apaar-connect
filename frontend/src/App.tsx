import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AppShell } from './components/layout/AppShell';
import { RoleGuard } from './components/layout/RoleGuard';

// Domain Pages
import { NationalDashboard } from './pages/NationalDashboard';
import { InstitutionPortal } from './pages/InstitutionPortal';
import { ReviewQueue } from './pages/ReviewQueue';
import { StudentPortal } from './pages/StudentPortal';
import { PublicVerifier } from './pages/PublicVerifier';
import { AuditLogViewer } from './pages/AuditLogViewer';

// Storybook-like Design System Component Lab
import { ComponentShowcase } from './pages/dev/ComponentShowcase';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30000,
    },
  },
});

/**
 * Handles automatic landing redirection based on the user's statutory role:
 * - AICTE users (Admin, Reviewer) -> Command Centre
 * - Institution users (Admin, Operator) -> Workspace
 * - Student -> Student Card
 * - Verifier -> Public Verifier
 * - Auditor -> Audit Trail
 */
const RoleLandingRedirect: React.FC = () => {
  const { getLandingPath } = useAuth();
  return <Navigate to={getLandingPath()} replace />;
};

const WorkspaceWrapper: React.FC = () => {
  const { user } = useAuth();
  return <InstitutionPortal institutionId={user.institutionId || 'INST-COEP-PUNE'} />;
};

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<AppShell />}>
              {/* Role-based root landing redirect */}
              <Route index element={<RoleLandingRedirect />} />

              {/* Command Centre (AICTE Admin, AICTE Reviewer, Auditor) */}
              <Route
                path="command-centre"
                element={
                  <RoleGuard allowedRoles={['AICTE_ADMIN', 'AICTE_REVIEWER', 'AUDITOR']}>
                    <NationalDashboard />
                  </RoleGuard>
                }
              />

              {/* Workspace (Institution Admin, Operator, AICTE Admin) */}
              <Route
                path="workspace"
                element={
                  <RoleGuard allowedRoles={['INSTITUTION_ADMIN', 'INSTITUTION_OPERATOR', 'AICTE_ADMIN']}>
                    <WorkspaceWrapper />
                  </RoleGuard>
                }
              />

              {/* Review Queue (AICTE Reviewer, AICTE Admin, Institution Admin, Auditor) */}
              <Route
                path="reviews"
                element={
                  <RoleGuard allowedRoles={['AICTE_ADMIN', 'AICTE_REVIEWER', 'INSTITUTION_ADMIN', 'AUDITOR']}>
                    <ReviewQueue />
                  </RoleGuard>
                }
              />

              {/* Student Card (Student, Institution Admin, AICTE Admin, Verifier) */}
              <Route
                path="student-card"
                element={
                  <RoleGuard allowedRoles={['STUDENT', 'INSTITUTION_ADMIN', 'AICTE_ADMIN', 'VERIFIER']}>
                    <StudentPortal />
                  </RoleGuard>
                }
              />

              {/* Public Verifier (Public access, Verifier, Student, all roles) */}
              <Route path="verify" element={<PublicVerifier />} />

              {/* Audit Trail (Auditor, AICTE Admin) */}
              <Route
                path="audit"
                element={
                  <RoleGuard allowedRoles={['AUDITOR', 'AICTE_ADMIN']}>
                    <AuditLogViewer />
                  </RoleGuard>
                }
              />

              {/* Storybook-like Component Showcase Showroom */}
              <Route path="dev/components" element={<ComponentShowcase />} />

              {/* Fallback */}
              <Route path="*" element={<RoleLandingRedirect />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
