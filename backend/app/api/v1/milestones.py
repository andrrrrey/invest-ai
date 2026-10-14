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
    note: str | None = None  # суть спора (для статуса disputed)


class ArbitrationIn(BaseModel):
    dispute: str | None = None


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
    if (body.status in ("paid", "disputed") and current_user.role not in ("cfo", "manager")):
        # Выполнение этапа подтверждают (или оспаривают) куратор/CFO/менеджер,
        # а не сам исполнитель.
        raise HTTPException(status_code=403, detail="Подтверждать выполнение этапа могут CFO и менеджер")
    result = write_service.update_milestone_status(
        db, project_id, index, body.status,
        actor_type="user", actor_id=str(current_user.id),
        extra={"disputeNote": (body.note or "").strip() or None} if body.status == "disputed" else None,
        actor_name=current_user.full_name,
    )
    return result


@router.post("/{project_id}/milestones/{index}/arbitration")
def arbitrate_milestone(
    project_id: int,
    index: int,
    body: ArbitrationIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI-арбитраж спора по этапу; результат сохраняется в этапе."""
    from .ai import _check_api_key, _ai_error
    from ...services import ai_service
    project = get_accessible_project(project_id, db, current_user)
    _check_api_key()
    milestones = list((project.smart_contract_data or {}).get("milestones") or [])
    if index < 0 or index >= len(milestones):
        raise HTTPException(status_code=404, detail="Этап не найден")
    ms = milestones[index]
    dispute = (body.dispute or ms.get("disputeNote") or "").strip()
    try:
        result = ai_service.arbitrate_milestone(project.name or "", ms, dispute)
    except Exception as exc:
        raise _ai_error(exc)
    import datetime as _dt
    result["at"] = _dt.datetime.utcnow().isoformat()
    scd = dict(project.smart_contract_data or {})
    milestones[index] = {**ms, "arbitration": result}
    scd["milestones"] = milestones
    project.smart_contract_data = scd
    db.commit()
    return result
