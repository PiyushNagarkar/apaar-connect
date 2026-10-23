from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SeatAllocationsDict(BaseModel):
    REGULAR: int = 0
    NRI: int = 0
    SUPERNUMERARY_FN_OCI_PIO: int = 0
    SUPERNUMERARY_GULF_WORKER_CHILD: int = 0
    OTHER: int = 0


class CreateApprovalRequest(BaseModel):
    institution_id: str
    programme: str
    branch: str
    academic_year: str
    approval_ref: str
    campus: str = "MAIN"
    shift: str = "FIRST"
    allocations: Optional[Dict[str, int]] = Field(default_factory=dict)
    rule_version: str = "AICTE_HANDBOOK_2024_25_V1"


class SupersedeApprovalRequest(BaseModel):
    change_reason: str
    programme: Optional[str] = None
    branch: Optional[str] = None
    campus: Optional[str] = None
    shift: Optional[str] = None
    academic_year: Optional[str] = None
    approval_ref: Optional[str] = None
    allocations: Optional[Dict[str, int]] = None


class CsvImportRequest(BaseModel):
    csv_content: str
    commit: bool = False


class RuleVersionCreateRequest(BaseModel):
    rule_version: str
    academic_year: str
    description: Optional[str] = None
    allowed_seat_types: List[str]
    handbook_reference: Optional[str] = "AICTE Approval Process Handbook (APH)"
    handbook_note: str = "Verify against the current AICTE Approval Process Handbook."
