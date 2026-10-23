"""
Analytics and Anomaly Detection Schemas (schemas/analytics.py).
Defines Pydantic models for:
- PART A: Deterministic Risk-Priority Score R = w1*S + w2*D + w3*L + w4*C + w5*I
- PART B: Data-Quality Score Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))
- System Overview and Institution Dashboard Analytics (Rule 11)
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PART A: Risk-Priority Score Schemas
# ---------------------------------------------------------------------------

class RiskScoreComponent(BaseModel):
    """
    Component in the Review-Priority Score:
    name: name of the term (e.g., seat_exception_severity)
    value: scaled 0-100 (null if unmeasurable)
    weight: renormalised weight (null if unmeasurable)
    contribution: weight * value (null if unmeasurable)
    """
    name: str
    value: Optional[float] = None
    weight: Optional[float] = None
    contribution: Optional[float] = None


class RiskPriorityScoreResponse(BaseModel):
    """
    Deterministic Review-Priority Score Response.
    Formula: R = w1*S + w2*D + w3*L + w4*C + w5*I
    Label: 'review-priority score, not a probability of misconduct'
    """
    score: Optional[float] = Field(
        None,
        description="Overall review-priority score scaled 0-100, or null if no components are measurable",
    )
    components: List[RiskScoreComponent] = Field(
        ...,
        description="Component breakdown with renormalised weights and contributions",
    )
    coverage: Optional[float] = Field(
        None,
        description="Identity service coverage rate (0-1), reporting share of records where identity check was available",
    )
    reason_codes: List[str] = Field(
        default_factory=list,
        description="Machine-readable codes explaining drivers of the priority score",
    )
    rule_version: str = Field(
        ...,
        description="AICTE Approval Process Handbook rule version reference",
    )
    label: str = Field(
        default="review-priority score, not a probability of misconduct",
        description="Mandatory regulatory label clarifying scores prioritise human review rather than assert guilt",
    )
    institution_id: Optional[str] = None
    programme: Optional[str] = None
    academic_year: Optional[str] = None


# ---------------------------------------------------------------------------
# PART B: Data-Quality Score Schemas
# ---------------------------------------------------------------------------

class DataQualityComponent(BaseModel):
    """
    Individual defect rate component for Q score.
    Symbol: M, V, D, A, T (all 0-1 rates with explicit denominators stated).
    """
    symbol: str
    name: str
    rate: float = Field(..., ge=0.0, le=1.0, description="Defect rate between 0 and 1")
    numerator: int = Field(..., ge=0, description="Defect count numerator")
    denominator: int = Field(..., ge=0, description="Total evaluations denominator")
    denominator_description: str = Field(..., description="Explicit description of the denominator")
    weight: float = Field(..., description="Weight penalty factor (35, 25, 20, 10, 10)")
    penalty: float = Field(..., description="Point deduction = rate * weight")


class DataQualityScoreResponse(BaseModel):
    """
    Data-Quality Score Response.
    Formula: Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))
    """
    score: float = Field(..., ge=0.0, le=100.0, description="Data-quality score Q from 0 to 100")
    grade: str = Field(..., description="Quality tier: EXCELLENT, GOOD, FAIR, POOR")
    formula: str = Field(
        default="Q = max(0, 100 - (35M + 25V + 20D + 10A + 10T))",
        description="Exact deterministic scoring formula",
    )
    components: Dict[str, DataQualityComponent] = Field(
        ...,
        description="Component defect rates alongside Q, stating each denominator explicitly",
    )
    total_records_evaluated: int = Field(..., ge=0)
    institution_id: Optional[str] = None
    programme: Optional[str] = None
    academic_year: Optional[str] = None


# ---------------------------------------------------------------------------
# Dashboard and Funnel Metrics Schemas (Rule 11)
# ---------------------------------------------------------------------------

class CategorySeatMetric(BaseModel):
    category: str
    quota_type: str
    approved_intake: int
    confirmed_admissions: int
    provisional_admissions: int = 0
    utilization_percentage: float
    is_overfilled: bool


class ProgramSeatMetric(BaseModel):
    program_id: str
    program_name: str
    total_approved_intake: int
    total_confirmed: int
    utilization_percentage: float
    category_breakdown: List[CategorySeatMetric]


class VerificationFunnelMetric(BaseModel):
    total_submitted: int
    confirmed_count: int
    under_review_count: int
    provisional_count: int
    rejected_count: int
    l1_pass_count: int
    l1_unavailable_count: int
    l1_fail_count: int
    l2_pass_count: int
    l2_fail_count: int
    l3_pass_count: int
    l3_fail_count: int


class ReviewQueueSummary(BaseModel):
    total_open_cases: int
    high_priority_cases: int
    duplicate_match_cases: int
    capacity_overflow_cases: int
    demographic_mismatch_cases: int
    unapproved_offering_cases: int


class SystemOverviewAnalytics(BaseModel):
    """Rule 11: National level system overview computed dynamically from database."""
    total_institutions: int
    active_institutions: int
    total_approved_programs: int
    total_statutory_intake: int
    total_confirmed_students: int
    overall_intake_utilization: float
    funnel: VerificationFunnelMetric
    review_queue: ReviewQueueSummary
    program_metrics: List[ProgramSeatMetric]
    synthetic_notice: str = Field(
        default="Synthetic data. Simulated APAAR service.",
        description="Rule 2: Synthetic data notice",
    )


class InstitutionDashboardAnalytics(BaseModel):
    """Rule 7 & Rule 11: Institution-specific dashboard analytics."""
    institution_id: str
    institution_name: str
    aicte_permanent_id: str
    approval_order_number: Optional[str] = None
    rule_version: Optional[str] = None
    total_approved_intake: int
    total_confirmed_students: int
    utilization_percentage: float
    funnel: VerificationFunnelMetric
    programs: List[ProgramSeatMetric]
    open_review_cases_count: int
    risk_priority: Optional[RiskPriorityScoreResponse] = None
    data_quality: Optional[DataQualityScoreResponse] = None
