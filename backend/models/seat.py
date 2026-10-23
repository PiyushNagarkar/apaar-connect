from sqlalchemy import Column, String, Integer, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
import enum
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class SeatType(str, enum.Enum):
    REGULAR = "REGULAR"
    NRI = "NRI"
    SUPERNUMERARY_FN_OCI_PIO = "SUPERNUMERARY_FN_OCI_PIO"
    SUPERNUMERARY_GULF_WORKER_CHILD = "SUPERNUMERARY_GULF_WORKER_CHILD"
    OTHER = "OTHER"


class SeatAllocation(Base, TimestampedUUIDMixin):
    """
    seat_allocations(approval_id, seat_type, approved_count, rule_version)
    seat_type enum: REGULAR, NRI, SUPERNUMERARY_FN_OCI_PIO, SUPERNUMERARY_GULF_WORKER_CHILD, OTHER
    """
    __tablename__ = "seat_allocations"

    approval_id = Column(String(36), ForeignKey("program_approvals.id"), nullable=False, index=True)
    seat_type = Column(Enum(SeatType), nullable=False, index=True)
    approved_count = Column(Integer, nullable=False, default=0)
    rule_version = Column(String(64), nullable=False)  # Rule 3

    approval = relationship("ProgramApproval", back_populates="seat_allocations")

    __table_args__ = (
        UniqueConstraint("approval_id", "seat_type", name="uq_approval_seat_type"),
    )
