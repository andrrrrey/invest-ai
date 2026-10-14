"""Назначение сотрудников на роли согласования (C&B, казначей, юрист, ...)."""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ... import settings_store
from ...auth import get_current_user, require_cfo
from ...database import get_db
from ...models.user import User
from ...services import approval_roles

router = APIRouter(prefix="/approval-roles", tags=["approval-roles"])


@router.get("")
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return approval_roles.describe(db)


@router.get("/me")
def my_roles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"roles": approval_roles.roles_of(db, current_user)}


@router.put("")
def update_roles(
    body: Dict[str, Optional[int]],
    db: Session = Depends(get_db),
    _: User = Depends(require_cfo),
):
    """Назначить сотрудников на роли. ``null`` снимает назначение. Только CFO."""
    updates = {}
    for key, user_id in body.items():
        if key not in approval_roles.ASSIGNABLE_ROLES:
            raise HTTPException(status_code=400, detail=f"Неизвестная роль: {key}")
        if user_id is not None:
            u = db.get(User, user_id)
            if u is None or not u.is_active:
                raise HTTPException(status_code=400, detail="Сотрудник не найден или неактивен")
        updates[key] = user_id
    settings_store.set_approval_roles(updates)
    return approval_roles.describe(db)
