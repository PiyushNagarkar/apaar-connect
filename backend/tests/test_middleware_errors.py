import pytest
from fastapi import APIRouter
from backend.main import app
from backend.schemas.errors import AppException, InvalidStateTransitionError

# Register a temporary test router on the app to test error responses
error_simulation_router = APIRouter(prefix="/api/test-errors", tags=["Testing"])


@error_simulation_router.get("/custom-exception")
def raise_custom_exception():
    raise AppException(
        code="SEAT_CAPACITY_EXCEEDED",
        message="Cannot admit student: approved seats full.",
        status_code=400,
        field="seat_type",
        details={"approved_count": 60, "enrolled_count": 60},
    )


@error_simulation_router.post("/invalid-transition")
def raise_invalid_transition():
    # Rule 12: Invalid state transitions return HTTP 409
    raise InvalidStateTransitionError(
        current_state="VERIFIED",
        target_state="DRAFT",
        reason="Verified credentials cannot revert to draft status without formal revocation.",
    )


app.include_router(error_simulation_router)


def test_request_id_middleware_generated(client):
    """Test that RequestIdMiddleware generates and attaches an X-Request-ID header."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"].startswith("req-")


def test_request_id_middleware_propagated(client):
    """Test that RequestIdMiddleware preserves a caller-supplied X-Request-ID."""
    custom_id = "req-custom-client-trace-12345"
    response = client.get("/api/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


def test_global_exception_handler_structured_format(client):
    """Test structured error format: {code, message, field, details}."""
    response = client.get("/api/test-errors/custom-exception")
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "SEAT_CAPACITY_EXCEEDED"
    assert "Cannot admit student" in data["message"]
    assert data["field"] == "seat_type"
    assert data["details"]["approved_count"] == 60


def test_invalid_lifecycle_transition_returns_409(client):
    """Rule 12: Test that invalid state transitions return HTTP 409 Conflict."""
    response = client.post("/api/test-errors/invalid-transition")
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "INVALID_STATE_TRANSITION"
    assert data["field"] == "status"
    assert data["details"]["current_state"] == "VERIFIED"
    assert data["details"]["target_state"] == "DRAFT"
