from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class FactEntry(Base):
    __tablename__ = "fact_entries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)       # 1–12
    metric_name = Column(String, nullable=False)
    plan_value = Column(Float, nullable=True)
    fact_value = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="fact_entries")

    __table_args__ = (
        UniqueConstraint("project_id", "year", "month", "metric_name", name="uq_fact_entry"),
    )
