from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class ProjectBase(BaseModel):
    project_type: str = "investment"
    name: Optional[str] = None
    business_unit: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    stage: Optional[str] = None
    start_date: Optional[str] = None
    platform: Optional[str] = None
    financial_model: Optional[Any] = None
    risks_data: Optional[Any] = None
    value_score_data: Optional[Any] = None
    decision_route: Optional[str] = None
    smart_contract_data: Optional[Any] = None
    status: str = "draft"


class ProjectCreate(ProjectBase):
    # CFO может завести заявку за другого сотрудника — тогда указывается id
    # ответственного (владельца). Для остальных ролей поле игнорируется.
    owner_user_id: Optional[int] = None


class ProjectUpdate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    id: int
    user_id: Optional[int] = None
    metrics: Optional[Any] = None
    rejection_reason: Optional[str] = None
    status_history: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
