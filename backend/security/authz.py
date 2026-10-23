"""
Authentication and Authorization Dependencies.
Implements:
- JWT Token extraction (Authorization header Bearer token and HttpOnly cookie access_token)
- Role verification (require_roles)
- Institution Scoping (institution_scope)
- Permission validation (require_permission)
"""
from typing import Any, Dict, List, Optional
from fastapi import Cookie, Depends, Header, Request
from pydantic import BaseModel

from backend.schemas.errors import AppException
from backend.security.crypto import decode_jwt, ExpiredTokenError, InvalidTokenError
from backend.security.permissions import (
    PERMISSION_MATRIX,
    has_permission,
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
)


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Authentication required or invalid credentials."):
        super().__init__(code="UNAUTHORIZED", message=message, status_code=401)


class ForbiddenError(AppException):
    def __init__(self, message: str = "Access forbidden: insufficient permissions or scope violation."):
        super().__init__(code="FORBIDDEN", message=message, status_code=403)


class UserPrincipal(BaseModel):
    user_id: str
    role: str
    email: Optional[str] = None
    institution_id: Optional[str] = None
    student_id: Optional[str] = None


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None),
    x_mock_role: Optional[str] = Header(None, alias="X-Mock-Role"),
    x_mock_institution_id: Optional[str] = Header(None, alias="X-Mock-Institution-Id"),
    x_mock_user_id: Optional[str] = Header(None, alias="X-Mock-User-Id"),
    x_mock_student_id: Optional[str] = Header(None, alias="X-Mock-Student-Id"),
) -> UserPrincipal:
    """
    Extracts authenticated user from:
    1. Authorization: Bearer <token> header
    2. HttpOnly Cookie: access_token
    3. X-Mock-Role header (for testing/development)
    Raises 401 if token is expired or invalid.
    """
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ")[1]
    elif access_token:
        raw_token = access_token

    if raw_token:
        payload = decode_jwt(raw_token)  # Will raise ExpiredTokenError (401) or InvalidTokenError (401)
        if not payload or "sub" not in payload:
            raise UnauthorizedError("Invalid token payload.")
        return UserPrincipal(
            user_id=payload.get("sub", "anonymous"),
            email=payload.get("email"),
            role=payload.get("role", ROLE_VERIFIER),
            institution_id=payload.get("institution_id"),
            student_id=payload.get("student_id"),
        )

    # Mock Role header (for quick manual testing / dev role switcher)
    if x_mock_role:
        return UserPrincipal(
            user_id=x_mock_user_id or f"user-{x_mock_role.lower()}-01",
            email=f"{x_mock_role.lower()}@demo.aicte.gov.in",
            role=x_mock_role.upper(),
            institution_id=x_mock_institution_id,
            student_id=x_mock_student_id,
        )

    # Fallback to public verifier if no token is provided
    return UserPrincipal(
        user_id="public-verifier",
        email=None,
        role=ROLE_VERIFIER,
        institution_id=None,
    )


def require_authenticated_user(user: UserPrincipal = Depends(get_current_user)) -> UserPrincipal:
    """Ensures caller has logged in with an active authenticated session."""
    if user.user_id == "public-verifier" and user.role == ROLE_VERIFIER and not user.email:
        raise UnauthorizedError("Authentication token is required for this endpoint.")
    return user


def require_roles(*allowed_roles: str):
    """
    Reusable FastAPI dependency that enforces caller's role against allowed roles.
    Raises HTTP 403 Forbidden if user lacks permitted role.
    """
    async def role_checker(user: UserPrincipal = Depends(require_authenticated_user)) -> UserPrincipal:
        if user.role not in allowed_roles:
            raise ForbiddenError(f"Role '{user.role}' is not authorized. Allowed: {list(allowed_roles)}")
        return user
    return role_checker


def require_permission(action: str):
    """
    FastAPI dependency checking that the authenticated role has the specified permission.
    Raises HTTP 403 Forbidden if action is not permitted for caller's role.
    """
    async def permission_checker(user: UserPrincipal = Depends(require_authenticated_user)) -> UserPrincipal:
        if not has_permission(user.role, action):
            raise ForbiddenError(f"Role '{user.role}' lacks permission for action '{action}'.")
        return user
    return permission_checker


class InstitutionScope:
    """
    Scoping wrapper enforcing Rule 7:
    Institution users automatically get a filter on institution_id.
    Never trust institution_id from the request body or URL for scoping.
    """
    def __init__(self, user: UserPrincipal):
        self.user = user
        self.role = user.role
        self.is_institution_user = user.role in [ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR]
        self.institution_id = user.institution_id if self.is_institution_user else None

    def validate_access(self, target_institution_id: Optional[str]) -> str:
        """
        Validates target institution access.
        If caller is an institution user, strictly enforces target_institution_id == user.institution_id.
        """
        if self.is_institution_user:
            if not self.user.institution_id:
                raise ForbiddenError("Institution user is not assigned to any institution.")
            if target_institution_id and target_institution_id != self.user.institution_id:
                raise ForbiddenError(
                    f"Scope violation: User belongs to institution '{self.user.institution_id}', "
                    f"and cannot access institution '{target_institution_id}'."
                )
            return self.user.institution_id

        if self.user.role == ROLE_STUDENT:
            raise ForbiddenError("Student accounts are not authorized for institutional management.")

        # AICTE Central roles (ADMIN, REVIEWER, AUDITOR) can access any institution
        return target_institution_id or ""

    def filter_query(self, query, model_class):
        """Automatically appends institution_id filter to SQLAlchemy queries."""
        if self.is_institution_user:
            return query.filter(model_class.institution_id == self.user.institution_id)
        return query


async def institution_scope(user: UserPrincipal = Depends(require_authenticated_user)) -> InstitutionScope:
    """
    Reusable dependency that every protected endpoint uses to guarantee institution data isolation.
    """
    return InstitutionScope(user)
