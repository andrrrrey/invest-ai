from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.notification import Notification
from ...auth import get_current_user

router = APIRouter(tags=["notifications"])


class NotificationRead(BaseModel):
    id: int
    title: str
    message: str
    link: str | None
    is_read: bool
    created_at: datetime
    project_id: int | None

    class Config:
        from_attributes = True


@router.get("/notifications/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .count()
    )
    return {"count": count}


@router.get("/notifications", response_model=List[NotificationRead])
def list_notifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return rows


# NOTE: read-all must be registered BEFORE /{id}/read to avoid FastAPI
# treating "read-all" as an integer path parameter.
@router.patch("/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"success": True}


@router.patch("/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    n = db.get(Notification, notification_id)
    if not n or n.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    n.is_read = True
    db.commit()
    return {"success": True}


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    db.delete(n)
    db.commit()
