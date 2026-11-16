"""Личные токены для подключения ИИ-программ (Claude и др.) по MCP.

Пользователь с ролью CEO/CFO/менеджер сам создаёт и отзывает свои токены в
профиле — без DevOps и перезапуска. CFO видит и может отозвать токены всех.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...services import mcp_token_service

router = APIRouter(prefix="/mcp-tokens", tags=["mcp"])


class TokenCreate(BaseModel):
    name: Optional[str] = None


@router.get("/")
def list_my_tokens(
    all: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Свои действующие токены; CFO с ``?all=true`` — токены всех пользователей."""
    if all:
        if user.role != "cfo":
            raise HTTPException(status_code=403, detail="Только для CFO")
        items = mcp_token_service.list_tokens(db)
    else:
        items = mcp_token_service.list_tokens(db, user)
    return {"allowed": mcp_token_service.can_use_mcp(user), "items": items}


@router.post("/")
def create_token(
    body: TokenCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Создать токен. Сам токен возвращается ОДИН раз — сохранить его позже нельзя."""
    try:
        row, raw = mcp_token_service.create_token(db, user, body.name or "")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data = mcp_token_service.to_dict(row)
    data["token"] = raw
    return data


@router.delete("/{token_id}")
def revoke_token(
    token_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Отозвать свой токен (CFO — любой). Действует сразу."""
    try:
        mcp_token_service.revoke_token(db, token_id, user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
