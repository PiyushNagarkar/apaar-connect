
import uuid
from contextvars import ContextVar
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.database import Base, engine
from backend.schemas.errors import AppException
from backend.api import api_router
from backend.api.credentials import router as credentials_router
import backend.models  # Register database models


request_id_ctx: ContextVar[str] = ContextVar(
    "request_id_ctx",
    default="SYSTEM_INITIAL",
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to each request and response."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or (
            f"req-{uuid.uuid4().hex[:12]}"
        )
        request.state.request_id = req_id
        token = request_id_ctx.set(req_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    content = {
        "code": exc.code,
        "message": exc.message,
    }
    if exc.field is not None:
        content["field"] = exc.field
    if exc.details is not None:
        content["details"] = exc.details

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    loc = first_error.get("loc", [])
    field = str(loc[-1]) if loc else None
    message = first_error.get("msg", "Request validation failed.")

    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": message,
            "field": field,
            "details": {"validation_errors": errors},
        },
    )


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
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
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="APAAR Connect API (AICTE India)",
    version="1.0.0",
    description=(
        "Unified Student Admission Record Verification and "
        "Compliance Platform. "
        "NOTICE: All data is synthetic. "
        "Simulated APAAR service (MOCK_APAAR_V1)."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(
    RequestValidationError,
    validation_exception_handler,
)
app.add_exception_handler(Exception, generic_exception_handler)

# The API router already includes the health router.
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")

# Keep credential endpoints at their existing root-level paths.
app.include_router(credentials_router)


@app.get("/")
def root():
    return {
        "service": "APAAR Connect Backend",
        "status": "OPERATIONAL",
        "version": "1.0.0",
        "mock_adapter": "MOCK_APAAR_V1",
        "synthetic_notice": (
            "Synthetic data. Simulated APAAR service."
        ),
    }
