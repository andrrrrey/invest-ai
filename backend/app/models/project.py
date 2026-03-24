from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    # Owner FK (nullable for backward compat with existing rows)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User", back_populates="projects")

    # Step 1
    project_type = Column(String, default="investment")  # investment | operational

    # Step 2
    name = Column(String, nullable=True)
    business_unit = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    # Step 3 — general
    owner = Column(String, nullable=True)
    stage = Column(String, nullable=True)
    start_date = Column(String, nullable=True)
    platform = Column(String, nullable=True)

    # Step 3 — full financial model stored as JSON
    financial_model = Column(JSON, nullable=True)

    # Cached calculated metrics
    metrics = Column(JSON, nullable=True)

    # Step 4 — AI-generated
    risks_data = Column(JSON, nullable=True)

    # Operational type (1.2) specific fields
    value_score_data = Column(JSON, nullable=True)   # Value Score inputs + calculated result
    decision_route = Column(String, nullable=True)   # fast_track | efficiency_play | backlog_stop | manual_review

    # Workflow status
    status = Column(String, default="draft")  # draft | pending_approval | approved | rejected

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
