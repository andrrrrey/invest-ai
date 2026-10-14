"""Роли согласующих в маршрутах контрактов и приказов.

Сотрудник на роль назначается в настройках (``settings_store.approval_roles``).
Для ролей «финансовый директор» и «CEO» без явного назначения используется
первый активный пользователь с системной ролью ``cfo`` / ``ceo`` (служебный
аккаунт бота исключается).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .. import settings_store
from ..models.user import User

ROLE_LABELS: Dict[str, str] = {
    "cb": "C&B",
    "customer": "Заказчик",
    "treasurer": "Казначей системы Coin",
    "cfo": "Финансовый директор",
    "lawyer": "Юрист",
    "ceo": "CEO",
}

# Роли, назначаемые в настройках (заказчик выбирается в самом контракте).
ASSIGNABLE_ROLES = ("cb", "treasurer", "cfo", "lawyer", "ceo")

_FALLBACK_SYSTEM_ROLE = {"cfo": "cfo", "ceo": "ceo"}


def _bot_email() -> str:
    from ..config import settings
    return settings.HERMES_BOT_EMAIL


def _active(db: Session, user_id: Optional[int]) -> Optional[User]:
    if not user_id:
        return None
    u = db.get(User, user_id)
    return u if u is not None and u.is_active else None


def user_for(db: Session, role_key: str) -> Optional[User]:
    """Сотрудник, назначенный на роль (или фолбэк для cfo/ceo)."""
    assigned = _active(db, settings_store.get_approval_roles().get(role_key))
    if assigned is not None:
        return assigned
    system_role = _FALLBACK_SYSTEM_ROLE.get(role_key)
    if system_role:
        return (
            db.query(User)
            .filter(User.role == system_role, User.is_active == True)  # noqa: E712
            .filter(User.email != _bot_email())
            .order_by(User.id)
            .first()
        )
    return None


def roles_of(db: Session, user: User) -> List[str]:
    """Роли согласования, которые сейчас выполняет пользователь."""
    return [key for key in ASSIGNABLE_ROLES if (u := user_for(db, key)) is not None and u.id == user.id]


def describe(db: Session) -> List[dict]:
    """Назначения для UI настроек и карточки контракта."""
    explicit = settings_store.get_approval_roles()
    out = []
    for key in ASSIGNABLE_ROLES:
        u = user_for(db, key)
        out.append({
            "role": key,
            "label": ROLE_LABELS[key],
            "user_id": u.id if u else None,
            "full_name": u.full_name if u else None,
            "explicit": bool(explicit.get(key)),
        })
    return out
