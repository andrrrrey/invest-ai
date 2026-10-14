"""Адресные уведомления по контрактам: в приложении + личное сообщение
от бота (Баффет/Hermes) в Mattermost.

Все отправки «мягкие»: ошибка Mattermost не ломает основную операцию.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.user import User
from . import links, mattermost_service
from .notification_service import create_notification

logger = logging.getLogger("hermes.contracts")


def card_path(project: Project, anchor: Optional[str] = None) -> str:
    path = links.project_path(project.project_type, project.id)
    return f"{path}#{anchor}" if anchor else path


def card_url(project: Project, anchor: Optional[str] = None) -> Optional[str]:
    base = links.app_base_url()
    return f"{base}{card_path(project, anchor)}" if base else None


def notify_user(
    db: Session,
    user: Optional[User],
    *,
    project: Project,
    title: str,
    message: str,
    anchor: Optional[str] = None,
    mm_attachments: Optional[list] = None,
    commit: bool = True,
) -> None:
    """Уведомить пользователя в приложении и личным сообщением в Mattermost."""
    if user is None or not user.is_active:
        return
    try:
        create_notification(
            db,
            user_id=user.id,
            title=title,
            message=message,
            project_id=project.id,
            link=card_path(project, anchor),
        )
        if commit:
            db.commit()
    except Exception:
        logger.exception("In-app notification failed (user %s, project %s)", user.id, project.id)

    if not mattermost_service.is_configured():
        return
    try:
        url = card_url(project, anchor)
        text = f"**{title}**\n{message}"
        if url:
            text += f"\n[Открыть]({url})"
        mattermost_service.post_to_email(
            mattermost_service.mattermost_email(user), text, attachments=mm_attachments
        )
    except Exception:
        logger.exception("Mattermost DM failed (user %s)", user.id)


def notify_assigned_responsible(db: Session, project: Project, actor: User, target: User) -> None:
    """Сотрудник назначен ответственным (контракт заведён или передан за него)."""
    if target is None or actor is None or target.id == actor.id:
        return
    notify_user(
        db,
        target,
        project=project,
        title="Вы назначены ответственным",
        message=f"{links.label_for(project)} «{project.name or 'без названия'}» — "
                f"ответственный назначен: {actor.full_name}",
    )
