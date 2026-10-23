from fastapi import APIRouter
from backend.api.health import router as health_router
from backend.api.auth import router as auth_router
from backend.api.enrollments import router as enrollments_router
from backend.api.students import router as students_router

from backend.api.approvals import admin_router as approvals_admin_router, general_router as approvals_general_router
from backend.api.identity import identity_router, students_identity_router
from backend.api.submissions import submissions_router
from backend.api.duplicates import router as duplicates_router
from backend.api.review_cases import router as review_cases_router
from backend.api.correction_requests import router as correction_requests_router
from backend.api.analytics import router as analytics_router
from backend.api.credentials import router as credentials_router
from backend.api.privacy import router as privacy_router
from backend.api.evidence import router as evidence_router
from backend.api.audit import router as audit_router
from backend.api.institutions import router as institutions_router
from backend.api.reports import router as reports_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(enrollments_router)
api_router.include_router(students_router)
api_router.include_router(approvals_admin_router)
api_router.include_router(approvals_general_router)
api_router.include_router(identity_router)
api_router.include_router(students_identity_router)
api_router.include_router(submissions_router)
api_router.include_router(duplicates_router)
api_router.include_router(review_cases_router)
api_router.include_router(correction_requests_router)
api_router.include_router(analytics_router)
api_router.include_router(credentials_router)
api_router.include_router(privacy_router)
api_router.include_router(evidence_router)
api_router.include_router(audit_router)
api_router.include_router(institutions_router)
api_router.include_router(reports_router)

__all__ = ["api_router"]




