from typing import Any, Dict, Optional
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    field: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class AppException(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        self.details = details or {}
        super().__init__(message)


class InvalidStateTransitionError(AppException):
    """Rule 12: Invalid state transitions return HTTP 409 Conflict."""
    def __init__(self, current_state: str, target_state: str, reason: str = ""):
        super().__init__(
            code="INVALID_STATE_TRANSITION",
            message=f"Transition from '{current_state}' to '{target_state}' is not permitted. {reason}".strip(),
            status_code=409,
            field="status",
            details={"current_state": current_state, "target_state": target_state},
        )


class ConflictError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=409,
            details=details,
        )


class NotFoundError(AppException):
    def __init__(self, message: str):
        super().__init__(
            code="NOT_FOUND",
            message=message,
            status_code=404,
        )


class BadRequestError(AppException):
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="BAD_REQUEST",
            message=message,
            status_code=400,
            field=field,
            details=details,
        )


class ForbiddenError(AppException):
    def __init__(self, message: str = "Access forbidden: insufficient permissions or scope violation.", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="FORBIDDEN",
            message=message,
            status_code=403,
            details=details,
        )

