"""Маршрут согласования контракта / приказа и полная история изменений."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models.project_change import ProjectChange
from ...models.user import User
from ...services import approval_roles, route_service
from .projects import get_accessible_project

router = APIRouter(prefix="/projects", tags=["approval-route"])

_STATUS_LABELS = {
    "draft": "Черновик",
    "pending_approval": "Отправлен на согласование",
    "approved": "Согласован",
    "rejected": "Отклонён",
    "rework_needed": "Возвращён на доработку",
}


class DecisionIn(BaseModel):
    decision: str  # approve | rework
    comment: Optional[str] = None
    nav_rate: Optional[float] = None


@router.get("/{project_id}/route")
def get_route(
    project_id: int,
    route: str = "contract",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if route not in route_service.ROUTES:
        raise HTTPException(status_code=400, detail="Неизвестный маршрут")
    project = get_accessible_project(project_id, db, current_user)
    return route_service.route_state(db, project, route, current_user)


@router.post("/{project_id}/route/steps/{step_id}/decision")
def decide_step(
    project_id: int,
    step_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_accessible_project(project_id, db, current_user)
    from ...models.approval_step import ApprovalStep
    step = db.get(ApprovalStep, step_id)
    if step is None or step.project_id != project_id:
        raise HTTPException(status_code=404, detail="Этап согласования не найден")
    if body.decision == "rework" and not (body.comment or "").strip():
        raise HTTPException(status_code=400, detail="Укажите, что нужно доработать")
    route_service.decide(db, step_id, current_user, body.decision, body.comment, nav_rate=body.nav_rate)
    db.refresh(project)
    return route_service.route_state(db, project, step.route, current_user)


@router.get("/{project_id}/history")
def project_history(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Хронология: статусы, этапы согласования (отправка/решение), изменения полей."""
    project = get_accessible_project(project_id, db, current_user)
    events = []
    if project.created_at:
        events.append({"ts": project.created_at.isoformat(), "kind": "created",
                       "title": "Создан", "by": None, "comment": None})
    for h in project.status_history or []:
        events.append({
            "ts": h.get("changed_at"), "kind": "status",
            "title": "Статус: " + _STATUS_LABELS.get(h.get("status"), h.get("status") or ""),
            "by": h.get("changed_by"), "comment": h.get("comment"),
        })
    for s in route_service.all_steps(db, project.id):
        role = approval_roles.ROLE_LABELS.get(s.role_key, s.role_key)
        what = "приказ" if s.route == "order" else "контракт"
        if s.sent_at:
            events.append({
                "ts": s.sent_at.isoformat(), "kind": "route_sent",
                "title": f"Отправлен на согласование ({what}): {role}",
                "by": s.assignee.full_name if s.assignee else None, "comment": None,
                "route": s.route, "cycle": s.cycle,
            })
        if s.decided_at:
            verdict = "согласовано" if s.status == "approved" else "возвращено на доработку"
            events.append({
                "ts": s.decided_at.isoformat(), "kind": "route_" + s.status,
                "title": f"{role}: {verdict}" + (" (приказ)" if s.route == "order" else ""),
                "by": s.decided_by.full_name if s.decided_by else None, "comment": s.comment,
                "route": s.route, "cycle": s.cycle,
            })
    changes = (
        db.query(ProjectChange)
        .filter(ProjectChange.project_id == project.id)
        .order_by(ProjectChange.created_at)
        .all()
    )
    for c in changes:
        events.append({
            "ts": c.created_at.isoformat() if c.created_at else None, "kind": "change",
            "title": f"Изменено: {c.label or c.field}",
            "by": c.user.full_name if c.user else None,
            "old": c.old_value, "new": c.new_value, "comment": None,
        })
    events.sort(key=lambda e: e["ts"] or "", reverse=True)
    return events
