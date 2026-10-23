from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def healthcheck():
    """
    Health check endpoint.
    Acceptance check: GET /api/health returns ok.
    """
    return {
        "status": "ok",
        "mock_adapter": "MOCK_APAAR_V1",
        "synthetic": True,
        "service": "APAAR Connect Backend",
        "version": "1.0.0",
    }
