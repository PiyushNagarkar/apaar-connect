import uuid
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.database import Base, engine
from backend.schemas.errors import AppException
from backend.api import api_router
import backend.models  # Ensure all 15 models are registered with Base.metadata

# ContextVar for tracing request_id across async functions
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="SYSTEM_INITIAL")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Request ID Middleware: assigns a unique UUID to each request, stores it on
    request.state.request_id, propagates via ContextVar, and returns it in X-Request-ID header.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = req_id
        token = request_id_ctx.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)


# Global Exception Handlers returning structured error format
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    content = {
        "code": exc.code,
        "message": exc.message,
    }
    if exc.field is not None:
        content["field"] = exc.field
    if exc.details is not None:
        content["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    loc = first_error.get("loc", [])
    field = str(loc[-1]) if loc else None
    msg = first_error.get("msg", "Request validation failed.")
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": msg,
            "field": field,
            "details": {"validation_errors": errors},
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected server error occurred.",
            "details": {"error": str(exc)},
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup if not already created
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="APAAR Connect API (AICTE India)",
    version="1.0.0",
    description=(
        "Unified Student Admission Record Verification and Compliance Platform. "
        "NOTICE: All data is synthetic. Simulated APAAR service (MOCK_APAAR_V1)."
    ),
    lifespan=lifespan,
)

# 1. Request ID Middleware
app.add_middleware(RequestIdMiddleware)

# 2. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# 3. Global Exception Handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 4. Include API routers under /api, /api/v1, and root routes (for direct /verify/{public_ref} QR scans)
from backend.api.credentials import router as credentials_router
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")
app.include_router(credentials_router)


@app.get("/")
def root():
    return {
        "service": "APAAR Connect Backend",
        "status": "OPERATIONAL",
        "version": "1.0.0",
        "mock_adapter": "MOCK_APAAR_V1",
        "synthetic_notice": "Synthetic data. Simulated APAAR service.",
    }
