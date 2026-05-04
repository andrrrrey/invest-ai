from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.project import Project
from ...models.tranche import Tranche, TriggerChecklistItem, TrancheHistory
from ...auth import get_current_user, require_approver
from ...services.notification_service import notify_approvers

router = APIRouter(tags=["tranches"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class TrancheCreate(BaseModel):
    amount: float
    planned_date: Optional[str] = None
    description: Optional[str] = None
    order_index: int = 0


class TrancheUpdate(BaseModel):
    amount: Optional[float] = None
    planned_date: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = None


class TrancheRead(BaseModel):
    id: int
    project_id: int
    amount: float
    planned_date: Optional[str]
    status: str
    description: Optional[str]
    order_index: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChecklistItemIn(BaseModel):
    id: Optional[int] = None
    metric_name: str
    target_value: Optional[str] = None
    actual_value: Optional[str] = None
    is_met: bool = False
    notes: Optional[str] = None


class ChecklistItemRead(BaseModel):
    id: int
    metric_name: str
    target_value: Optional[str]
    actual_value: Optional[str]
    is_met: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class StatusChange(BaseModel):
    status: str  # approved | paid
    comment: Optional[str] = None


class TrancheHistoryRead(BaseModel):
    id: int
    event_type: str
    comment: Optional[str]
    created_at: datetime
    actor_name: str

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_tranche_or_404(db: Session, tranche_id: int) -> Tranche:
    t = db.get(Tranche, tranche_id)
    if not t:
        raise HTTPException(status_code=404, detail="Транш не найден")
    return t


# ── Project tranches ──────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/tranches", response_model=List[TrancheRead])
def list_tranches(
    project_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    return db.query(Tranche).filter(Tranche.project_id == project_id).order_by(Tranche.order_index).all()


@router.post("/projects/{project_id}/tranches", response_model=TrancheRead, status_code=201)
def create_tranche(
    project_id: int,
    body: TrancheCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    t = Tranche(project_id=project_id, **body.model_dump())
    db.add(t)
    db.flush()
    db.add(TrancheHistory(
        tranche_id=t.id, user_id=current_user.id,
        event_type="created", comment="Транш создан",
    ))
    db.commit()
    db.refresh(t)
    return t


# ── Single tranche ────────────────────────────────────────────────────────────

@router.put("/tranches/{tranche_id}", response_model=TrancheRead)
def update_tranche(
    tranche_id: int,
    body: TrancheUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    t = _get_tranche_or_404(db, tranche_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/tranches/{tranche_id}", status_code=204)
def delete_tranche(
    tranche_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    t = _get_tranche_or_404(db, tranche_id)
    db.delete(t)
    db.commit()


@router.patch("/tranches/{tranche_id}/status", response_model=TrancheRead)
def change_tranche_status(
    tranche_id: int,
    body: StatusChange,
    db: Session = Depends(get_db),
    current_user=Depends(require_approver),
):
    t = _get_tranche_or_404(db, tranche_id)

    if body.status not in ("approved", "paid"):
        raise HTTPException(status_code=400, detail="Допустимые статусы: approved, paid")

    if body.status == "approved":
        items = t.checklist
        if items and not all(item.is_met for item in items):
            raise HTTPException(
                status_code=400,
                detail="Не все триггеры выполнены. Отметьте выполнение всех метрик перед одобрением транша.",
            )

    t.status = body.status
    db.add(TrancheHistory(
        tranche_id=t.id, user_id=current_user.id,
        event_type="status_changed",
        comment=body.comment or f"Статус изменён на «{body.status}»",
    ))
    db.flush()

    # If paid — notify approvers about the next requested tranche
    if body.status == "paid":
        next_tranche = (
            db.query(Tranche)
            .filter(
                Tranche.project_id == t.project_id,
                Tranche.order_index > t.order_index,
                Tranche.status == "requested",
            )
            .order_by(Tranche.order_index)
            .first()
        )
        if next_tranche:
            project = db.get(Project, t.project_id)
            notify_approvers(
                db,
                project_id=t.project_id,
                project_name=project.name or f"Проект #{t.project_id}",
                applicant_name=f"следующий транш #{next_tranche.order_index + 1}",
            )

    db.commit()
    db.refresh(t)
    return t


# ── Checklist ─────────────────────────────────────────────────────────────────

@router.get("/tranches/{tranche_id}/triggers", response_model=List[ChecklistItemRead])
def get_triggers(
    tranche_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_tranche_or_404(db, tranche_id)
    return db.query(TriggerChecklistItem).filter(TriggerChecklistItem.tranche_id == tranche_id).all()


@router.put("/tranches/{tranche_id}/triggers", response_model=List[ChecklistItemRead])
def replace_triggers(
    tranche_id: int,
    items: List[ChecklistItemIn],
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    t = _get_tranche_or_404(db, tranche_id)
    # Delete existing and replace with new list
    db.query(TriggerChecklistItem).filter(TriggerChecklistItem.tranche_id == tranche_id).delete()
    new_items = []
    for item in items:
        ci = TriggerChecklistItem(
            tranche_id=tranche_id,
            metric_name=item.metric_name,
            target_value=item.target_value,
            actual_value=item.actual_value,
            is_met=item.is_met,
            notes=item.notes,
        )
        db.add(ci)
        new_items.append(ci)
    db.add(TrancheHistory(
        tranche_id=tranche_id, user_id=current_user.id,
        event_type="checklist_updated", comment="Чек-лист триггеров обновлён",
    ))
    db.commit()
    for ci in new_items:
        db.refresh(ci)
    return new_items


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/tranches/{tranche_id}/history", response_model=List[TrancheHistoryRead])
def get_history(
    tranche_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_tranche_or_404(db, tranche_id)
    rows = (
        db.query(TrancheHistory)
        .filter(TrancheHistory.tranche_id == tranche_id)
        .order_by(TrancheHistory.created_at.desc())
        .all()
    )
    return [
        TrancheHistoryRead(
            id=h.id,
            event_type=h.event_type,
            comment=h.comment,
            created_at=h.created_at,
            actor_name=h.user.full_name if h.user else "—",
        )
        for h in rows
    ]
