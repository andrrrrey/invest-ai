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


class MilestoneReportIn(BaseModel):
    report: str = ""


def _can_work_on(project, user: User) -> bool:
    """Исполнитель контракта: ответственный или автор (CFO/менеджер — любые).
    Заказчики и куратор видят контракт в режиме просмотра."""
    if user.role in ("cfo", "manager"):
        return True
    return user.role == "owner" and user.id in (project.user_id, project.created_by_id)


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
    project = get_accessible_project(project_id, db, current_user)
    if current_user.role == "ceo":
        raise HTTPException(status_code=403, detail="CEO не может изменять данные")
    if not _can_work_on(project, current_user):
        raise HTTPException(status_code=403, detail="Контракт доступен вам в режиме просмотра")
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


@router.put("/{project_id}/milestones/{index}/report")
def set_milestone_report(
    project_id: int,
    index: int,
    body: MilestoneReportIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Текстовый отчёт о выполнении этапа (необязательный). Пустой текст удаляет отчёт."""
    import datetime as _dt
    from ...services import change_log
    project = get_accessible_project(project_id, db, current_user)
    if not _can_work_on(project, current_user):
        raise HTTPException(status_code=403, detail="Отчёт по этапу фиксирует ответственный, автор контракта, CFO или менеджер")
    milestones = list((project.smart_contract_data or {}).get("milestones") or [])
    if index < 0 or index >= len(milestones):
        raise HTTPException(status_code=404, detail="Этап не найден")
    text = (body.report or "").strip()
    if len(text) > 10000:
        raise HTTPException(status_code=400, detail="Отчёт слишком длинный (не более 10 000 символов)")
    ms = dict(milestones[index])
    old = ms.get("report") or None
    if text:
        ms.update(report=text, reportBy=current_user.full_name,
                  reportAt=_dt.datetime.utcnow().isoformat())
    else:
        for k in ("report", "reportBy", "reportAt"):
            ms.pop(k, None)
    milestones[index] = ms
    scd = dict(project.smart_contract_data or {})
    scd["milestones"] = milestones
    project.smart_contract_data = scd
    if old != (text or None):
        change_log.log(db, project.id, current_user.id, f"milestones[{index}].report",
                       f"Отчёт по этапу «{ms.get('name') or ms.get('title') or index + 1}»",
                       old, text or None)
    db.commit()
    return ms


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
