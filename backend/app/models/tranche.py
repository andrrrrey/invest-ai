from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Tranche(Base):
    __tablename__ = "tranches"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    planned_date = Column(String, nullable=True)   # ISO date string YYYY-MM-DD
    status = Column(String, default="requested")   # requested | approved | paid
    description = Column(Text, nullable=True)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="tranches")
    checklist = relationship(
        "TriggerChecklistItem", back_populates="tranche",
        cascade="all, delete-orphan", order_by="TriggerChecklistItem.id"
    )
    history = relationship(
        "TrancheHistory", back_populates="tranche",
        cascade="all, delete-orphan", order_by="TrancheHistory.created_at"
    )


class TriggerChecklistItem(Base):
    __tablename__ = "tranche_checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    tranche_id = Column(Integer, ForeignKey("tranches.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name = Column(String, nullable=False)
    target_value = Column(String, nullable=True)
    actual_value = Column(String, nullable=True)
    is_met = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)

    tranche = relationship("Tranche", back_populates="checklist")


class TrancheHistory(Base):
    __tablename__ = "tranche_history"

    id = Column(Integer, primary_key=True, index=True)
    tranche_id = Column(Integer, ForeignKey("tranches.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # created | status_changed | checklist_updated
    event_type = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tranche = relationship("Tranche", back_populates="history")
    user = relationship("User")
