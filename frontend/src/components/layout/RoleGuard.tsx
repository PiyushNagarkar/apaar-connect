import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { SystemRole } from '../../types';
import { NoPermissionState } from '../design-system/NoPermissionState';

export interface RoleGuardProps {
  allowedRoles: SystemRole[];
  children: React.ReactNode;
}

export const RoleGuard: React.FC<RoleGuardProps> = ({ allowedRoles, children }) => {
  const { role, getLandingPath } = useAuth();
  const navigate = useNavigate();

  if (!allowedRoles.includes(role)) {
    return (
      <div className="py-8">
        <NoPermissionState
          currentRole={role}
          requiredRoles={allowedRoles}
          onNavigateHome={() => navigate(getLandingPath())}
        />
      </div>
    );
  }

  return <>{children}</>;
};

export default RoleGuard;
