"""
Authentication Endpoints:
- POST /api/auth/login
- POST /api/auth/logout
- GET /api/auth/me
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.schemas.auth import LoginRequest, LoginResponse, UserProfileResponse, UserSummary
from backend.schemas.errors import AppException
from backend.security.crypto import create_jwt, verify_password
from backend.security.authz import get_current_user, require_authenticated_user, UserPrincipal
from backend.security.permissions import PERMISSION_MATRIX
from backend.security.rate_limiter import login_rate_limiter
from backend.services.audit import record_audit_event

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    POST /api/auth/login:
    Validates user credentials, rate-limits brute force attempts, logs audit events,
    issues a short-lived (15 min) JWT, and sets an HttpOnly cookie.
    """
    client_ip = request.client.host if request.client else "unknown_client"
    rate_key = f"{client_ip}:{payload.email.lower()}"

    # 1. Rate limiting check
    login_rate_limiter.check(rate_key)

    # 2. Look up user
    user = db.query(User).filter(User.email == payload.email.strip().lower()).first()

    # 3. Verify user and password
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        login_rate_limiter.record_failure(rate_key)
        # Audit failed login attempt (Rule 9)
        record_audit_event(
            db=db,
            actor_id=payload.email,
            action="AUTH_LOGIN_FAILED",
            entity_type="USER",
            entity_id=payload.email,
            reason="Invalid credentials or inactive account",
            request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
        raise AppException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            status_code=401,
        )

    # 4. Successful login: reset rate limiter
    login_rate_limiter.reset(rate_key)

    # 5. Issue short-lived access token (15 mins)
    token_claims = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "institution_id": str(user.institution_id) if user.institution_id else None,
    }
    access_token = create_jwt(token_claims, expires_minutes=15)

    # 6. Set HttpOnly cookie for browser security
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=900,
        samesite="lax",
        secure=False,  # Can be True in production HTTPS
    )

    # 7. Audit log success
    record_audit_event(
        db=db,
        actor_id=str(user.id),
        action="AUTH_LOGIN_SUCCESS",
        entity_type="USER",
        entity_id=str(user.id),
        reason="User successfully authenticated",
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=900,
        user=UserSummary(
            id=str(user.id),
            email=user.email,
            role=user.role,
            institution_id=str(user.institution_id) if user.institution_id else None,
        ),
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /api/auth/logout:
    Clears HttpOnly access_token cookie and records audit event.
    """
    response.delete_cookie(key="access_token")

    if current_user.user_id != "public-verifier":
        record_audit_event(
            db=db,
            actor_id=current_user.user_id,
            action="AUTH_LOGOUT",
            entity_type="USER",
            entity_id=current_user.user_id,
            reason="User logged out session",
            request_id=getattr(request.state, "request_id", None),
        )
        db.commit()

    return {"status": "ok", "message": "Successfully logged out."}


@router.get("/me", response_model=UserProfileResponse)
def get_me(current_user: UserPrincipal = Depends(require_authenticated_user)):
    """
    GET /api/auth/me:
    Returns the authenticated user's profile, role, scope, and allowed actions from permission matrix.
    """
    permissions = sorted(list(PERMISSION_MATRIX.get(current_user.role, set())))
    return UserProfileResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        role=current_user.role,
        institution_id=current_user.institution_id,
        student_id=current_user.student_id,
        permissions=permissions,
    )
