"""
Гранулярное обновление статуса майлстоуна смарт-контракта.

Раньше статус майлстоуна менялся только в памяти фронтенда (verifyMilestone).
Этот endpoint делает изменение персистентным — и его же переиспользует
помощник Hermes через write-инструмент.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models.user import User
from ...services import write_service
from .projects import get_accessible_project

router = APIRouter(prefix="/projects", tags=["milestones"])


class MilestoneStatusIn(BaseModel):
    status: str


@router.patch("/{project_id}/milestones/{index}/status")
def set_milestone_status(
    project_id: int,
    index: int,
    body: MilestoneStatusIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Изменить статус майлстоуна. Заявитель — только для своих проектов
    (проверка в get_accessible_project); CFO/менеджер — для любых."""
    get_accessible_project(project_id, db, current_user)
    if current_user.role == "ceo":
        raise HTTPException(status_code=403, detail="CEO не может изменять данные")
    return write_service.update_milestone_status(
        db, project_id, index, body.status,
        actor_type="user", actor_id=str(current_user.id),
    )
