"""
Analytics & Compliance Dashboard Router (api/analytics.py).
Exposes REST endpoints for:
- GET /api/analytics/overview: National system overview (Rule 11)
- GET /api/analytics/institution/{institution_id}: Institution-scoped dashboard
- GET /api/analytics/risk-priority: PART A Review-Priority Score
- GET /api/analytics/data-quality: PART B Data-Quality Score
- GET /api/analytics/anomalies: Anomaly scanning and review queue flags
"""
from typing import Optional
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.analytics import (
    DataQualityScoreResponse,
    InstitutionDashboardAnalytics,
    RiskPriorityScoreResponse,
    SystemOverviewAnalytics,
)
from backend.security.authz import (
    UserPrincipal,
    get_current_user,
    institution_scope,
    require_roles,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
)
from backend.services.analytics_service import (
    compute_data_quality_score,
    get_institution_dashboard,
    get_programme_compliance_analytics,
    get_system_overview,
)
from backend.services.anomaly_detection import (
    compute_risk_priority_score,
    detect_duplicate_spikes,
    detect_seat_capacity_anomalies,
    scan_institution_anomalies,
)

router = APIRouter(prefix="/analytics", tags=["Analytics & Compliance Dashboard"])


@router.get("/overview", response_model=SystemOverviewAnalytics)
def get_national_overview(
    db: Session = Depends(get_db),
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    National system overview computed dynamically from database tables.
    Rule 11: No hard-coded demo numbers.
    Rule 2: Embeds synthetic data notice.
    """
    return get_system_overview(db)


@router.get("/institution/{institution_id}", response_model=InstitutionDashboardAnalytics)
def get_institution_analytics(
    institution_id: str = Path(...),
    db: Session = Depends(get_db),
    scope = Depends(institution_scope),
):
    """
    Institution-scoped seat utilization and verification funnel.
    Rule 7: Server-side check ensures caller cannot access other institutions.
    Rule 11: All figures computed dynamically from DB.
    """
    scope.validate_access(institution_id)
    return get_institution_dashboard(db, institution_id)


@router.get("/risk-priority", response_model=RiskPriorityScoreResponse)
def get_risk_priority_score(
    institution_id: str = Query(..., description="Institution ID"),
    programme: Optional[str] = Query(None, description="Academic Programme"),
    academic_year: Optional[str] = Query(None, description="Academic Year, e.g. 2024-2025"),
    rule_version: Optional[str] = Query(None, description="AICTE rule version"),
    db: Session = Depends(get_db),
    scope = Depends(institution_scope),
):
    """
    PART A: Deterministic Risk-Priority Score per institution-programme-year:
    R = w1*S + w2*D + w3*L + w4*C + w5*I
    Label: 'review-priority score, not a probability of misconduct'
    """
    scope.validate_access(institution_id)
    return compute_risk_priority_score(
        db=db,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
        rule_version=rule_version,
    )


@router.get("/data-quality", response_model=DataQualityScoreResponse)
def get_data_quality_score(
    institution_id: Optional[str] = Query(None, description="Institution ID"),
    programme: Optional[str] = Query(None, description="Academic Programme"),
    academic_year: Optional[str] = Query(None, description="Academic Year"),
    db: Session = Depends(get_db),
    scope = Depends(institution_scope),
):
    """
    PART B: Data-Quality Score:
    Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))
    States each denominator and returns component rates alongside Q.
    """
    if institution_id:
        scope.validate_access(institution_id)
    return compute_data_quality_score(
        db=db,
        institution_id=institution_id,
        programme=programme,
        academic_year=academic_year,
    )


@router.get("/anomalies")
def get_anomalies_scan(
    institution_id: Optional[str] = Query(None, description="Filter by Institution ID"),
    academic_year: Optional[str] = Query(None, description="Filter by Academic Year"),
    db: Session = Depends(get_db),
    current_user: UserPrincipal = Depends(get_current_user),
    scope = Depends(institution_scope),
):
    """
    Regulatory Anomaly Scanner:
    Identifies seat capacity overflows, duplicate identity spikes, and degraded coverage.
    """
    if institution_id:
        scope.validate_access(institution_id)
        return scan_institution_anomalies(db, institution_id, academic_year=academic_year)


    # National scan requires AICTE reviewer, admin, or auditor
    require_roles([ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_AUDITOR])(current_user)
    seat_anomalies = detect_seat_capacity_anomalies(db, academic_year=academic_year)
    duplicate_spikes = detect_duplicate_spikes(db)

    return {
        "seat_anomalies": seat_anomalies,
        "duplicate_spikes": duplicate_spikes,
        "total_anomalies": len(seat_anomalies) + len(duplicate_spikes),
    }
