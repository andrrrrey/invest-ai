"""Личные MCP-токены пользователей (подключение Claude и др. ИИ-программ).

Создавать токены могут только роли, которые и так видят весь портфель:
CEO, CFO и менеджер. Токен перестаёт работать, если его отозвали, если
пользователь деактивирован/удалён или его роль сменилась на недопустимую.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import settings
from ..models.mcp_token import McpToken
from ..models.user import User
from . import audit_service

ALLOWED_ROLES = ("ceo", "cfo", "manager")
TOKEN_PREFIX = "imcp_"
MAX_ACTIVE_TOKENS_PER_USER = 10
# Как часто обновлять last_used_at (не пишем в БД на каждый запрос).
_TOUCH_INTERVAL = timedelta(minutes=5)


def can_use_mcp(user: Optional[User]) -> bool:
    return bool(
        user is not None
        and user.is_active
        and user.role in ALLOWED_ROLES
        and user.email != settings.HERMES_BOT_EMAIL
    )


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_dict(t: McpToken, user: Optional[User] = None) -> dict:
    data = {
        "id": t.id,
        "name": t.name,
        "token_prefix": t.token_prefix,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "revoked": t.revoked_at is not None,
        "user_id": t.user_id,
    }
    if user is not None:
        data["user_name"] = user.full_name
        data["user_email"] = user.email
    return data


def create_token(db: Session, user: User, name: str) -> Tuple[McpToken, str]:
    """Создать токен. Возвращает (запись, сам токен — показать один раз)."""
    if not can_use_mcp(user):
        raise PermissionError("Подключение ИИ по MCP доступно только CEO, CFO и менеджерам")
    active = (
        db.query(McpToken)
        .filter(McpToken.user_id == user.id, McpToken.revoked_at.is_(None))
        .count()
    )
    if active >= MAX_ACTIVE_TOKENS_PER_USER:
        raise ValueError(
            f"Не больше {MAX_ACTIVE_TOKENS_PER_USER} действующих токенов. Отзовите ненужные."
        )
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = McpToken(
        user_id=user.id,
        name=(name or "").strip()[:100] or "Без названия",
        token_hash=_hash(raw),
        token_prefix=raw[: len(TOKEN_PREFIX) + 6],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_service.log_event(
        action="mcp.token_create", actor_type="user", actor_id=str(user.id),
        target_type="mcp_token", target_id=str(row.id), meta={"name": row.name},
    )
    return row, raw


def list_tokens(db: Session, user: Optional[User] = None, *, include_revoked: bool = False) -> List[dict]:
    """Токены пользователя (или всех, если ``user`` не задан — для CFO)."""
    q = db.query(McpToken, User).join(User, User.id == McpToken.user_id)
    if user is not None:
        q = q.filter(McpToken.user_id == user.id)
    if not include_revoked:
        q = q.filter(McpToken.revoked_at.is_(None))
    return [to_dict(t, u) for t, u in q.order_by(McpToken.id.desc()).all()]


def revoke_token(db: Session, token_id: int, actor: User) -> McpToken:
    row = db.query(McpToken).filter(McpToken.id == token_id).first()
    if row is None or (row.user_id != actor.id and actor.role != "cfo"):
        raise LookupError("Токен не найден")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        audit_service.log_event(
            action="mcp.token_revoke", actor_type="user", actor_id=str(actor.id),
            target_type="mcp_token", target_id=str(row.id),
            meta={"owner_user_id": row.user_id},
        )
    return row


def authenticate(db: Session, raw: Optional[str]) -> Optional[User]:
    """Пользователь по токену, если токен действителен и роль допустима."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    row = (
        db.query(McpToken)
        .filter(McpToken.token_hash == _hash(raw), McpToken.revoked_at.is_(None))
        .first()
    )
    if row is None:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if not can_use_mcp(user):
        return None
    now = datetime.now(timezone.utc)
    last = _aware(row.last_used_at)
    if last is None or now - last > _TOUCH_INTERVAL:
        row.last_used_at = now
        db.commit()
    return user
