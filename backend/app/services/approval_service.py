"""
Единая логика смены статуса проекта (согласование).

Одна и та же функция используется REST-эндпоинтом
(``PATCH /projects/{id}/status``) и обработчиком нажатий кнопок в Mattermost —
поэтому права, история статусов, in-app/email-уведомления и аудит работают
одинаково независимо от точки входа. Роли и порядок согласования не меняются:
согласуют CFO и менеджер, CEO — наблюдатель.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import List, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.user import User
from . import audit_service, mattermost_service
from .notification_service import notify_approvers, notify_owner
from .email_service import send_approval_request_emails, send_status_notification_email

logger = logging.getLogger("hermes.approval")

# Решение из карточки Mattermost -> целевой статус.
DECISION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "rework": "rework_needed",
}

_DONE_LABELS = {
    "approved": "согласована",
    "rejected": "отклонена",
    "rework_needed": "отправлена на доработку",
}


def check_permission(project: Project, new_status: str, actor: User) -> None:
    """Проверить право актора на переход (совпадает с прежней логикой эндпоинта)."""
    role = actor.role
    if new_status in ("approved", "rejected", "rework_needed"):
        if role not in ("cfo", "manager"):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Только CFO или Менеджер могут согласовывать/отклонять заявки",
            )
    elif new_status == "pending_approval":
        if role == "ceo":
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="CEO не может подавать заявки на согласование",
            )
        if role == "owner" and project.user_id != actor.id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому проекту",
            )
    elif new_status == "draft":
        if role == "owner" and project.user_id != actor.id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому проекту",
            )


def _notify(db: Session, project: Project, new_status: str, actor: User, project_name: str) -> None:
    # In-app
    try:
        if new_status == "pending_approval":
            notify_approvers(db, project.id, project_name, actor.full_name)
            db.commit()
        elif new_status in ("approved", "rejected", "draft", "rework_needed") and project.user_id:
            notify_owner(db, project.user_id, project.id, project_name, new_status)
            db.commit()
    except Exception:
        logger.exception("In-app notification failed for project %s", project.id)

    # Email (fire-and-forget)
    try:
        if new_status == "pending_approval":
            approvers = (
                db.query(User)
                .filter(User.role.in_(["cfo", "manager"]), User.is_active == True)  # noqa: E712
                .all()
            )
            recipients = [{"email": u.email, "full_name": u.full_name} for u in approvers]
            if recipients:
                send_approval_request_emails(recipients, project_name, actor.full_name)
        elif new_status in ("approved", "rejected", "draft", "rework_needed"):
            owner = db.get(User, project.user_id) if project.user_id else None
            if owner and owner.email:
                send_status_notification_email(owner.email, owner.full_name, project_name, new_status)
    except Exception:
        logger.exception("Email notification failed for project %s", project.id)


def _approver_emails(db: Session) -> List[str]:
    approvers = (
        db.query(User)
        .filter(User.role.in_(["cfo", "manager"]), User.is_active == True)  # noqa: E712
        .all()
    )
    # Используем Mattermost-email согласующего (с фолбэком на основной).
    return [e for e in (mattermost_service.mattermost_email(u) for u in approvers) if e]


# Лейблы статусов для личного уведомления заявителю о решении.
_OWNER_STATUS_LABELS = {
    "approved": "Утверждён",
    "rejected": "Отклонён",
    "rework_needed": "Отправлен на доработку",
    "draft": "Возвращён в черновик",
}

_BOT_NOT_CONFIGURED_MSG = (
    "Бот Mattermost не настроен — сообщение не отправлено. "
    "Заполните «URL сервера Mattermost» и «Токен бота» в Настройках."
)


def _notify_owner_decision_mm(db: Session, project: Project, new_status: str, project_name: str) -> None:
    """DM заявителю о принятом решении (согласован/отклонён/на доработку)."""
    if not mattermost_service.is_configured():
        logger.warning("%s (проект %s, статус %s)", _BOT_NOT_CONFIGURED_MSG, project.id, new_status)
        return
    owner = db.get(User, project.user_id) if project.user_id else None
    owner_email = mattermost_service.mattermost_email(owner)
    if not owner_email:
        return
    label = _OWNER_STATUS_LABELS.get(new_status, new_status)
    try:
        ok = mattermost_service.post_to_email(
            owner_email, f"Проект «{project_name}» — {label}."
        )
        audit_service.log_event(
            action="hermes.decision_notified",
            actor_type="hermes",
            result="ok" if ok else "error",
            target_type="project",
            target_id=str(project.id),
            meta={"new_status": new_status},
        )
    except Exception:
        logger.exception("Mattermost decision notification failed for project %s", project.id)


def _on_pending_approval(db: Session, project: Project, project_name: str, applicant_name: str) -> None:
    """Отправить карточку согласования ответственным и напоминание заявителю."""
    if not mattermost_service.is_configured():
        logger.warning("%s (проект %s, отправка на согласование)", _BOT_NOT_CONFIGURED_MSG, project.id)
        return
    try:
        sent = mattermost_service.send_approval_card(
            project.id, project_name, applicant_name, _approver_emails(db)
        )
        audit_service.log_event(
            action="hermes.approval_card_sent",
            actor_type="hermes",
            result="ok",
            target_type="project",
            target_id=str(project.id),
            meta={"cards_sent": sent},
        )
        # Напоминание заявителю обновить факт и статус майлстоунов.
        owner = db.get(User, project.user_id) if project.user_id else None
        owner_email = mattermost_service.mattermost_email(owner)
        if owner_email:
            mattermost_service.post_to_email(
                owner_email,
                f"Проект «{project_name}» отправлен на согласование. "
                "Пожалуйста, обновите фактические показатели и статус майлстоунов.",
            )
            audit_service.log_event(
                action="hermes.applicant_reminder",
                actor_type="hermes",
                result="ok",
                target_type="project",
                target_id=str(project.id),
            )
    except Exception:
        logger.exception("Mattermost approval hooks failed for project %s", project.id)


def apply_status_change(
    db: Session,
    project: Project,
    new_status: str,
    actor: User,
    *,
    actor_type: str = "user",
) -> Project:
    """Применить смену статуса: права, история, уведомления, карточки, аудит."""
    check_permission(project, new_status, actor)

    history = list(project.status_history or [])
    history.append(
        {
            "status": new_status,
            "changed_at": dt.datetime.utcnow().isoformat(),
            "changed_by": actor.full_name,
            "changed_by_id": actor.id,
        }
    )
    project.status = new_status
    project.status_history = history
    db.commit()
    db.refresh(project)

    project_name = project.name or "(без названия)"
    _notify(db, project, new_status, actor, project_name)

    audit_service.log_event(
        action="status.change",
        actor_type=actor_type,
        actor_id=str(actor.id),
        result="ok",
        target_type="project",
        target_id=str(project.id),
        meta={"new_status": new_status},
    )

    if new_status == "pending_approval":
        _on_pending_approval(db, project, project_name, actor.full_name)
    elif new_status in ("approved", "rejected", "rework_needed"):
        # Личное уведомление заявителю о решении в Mattermost.
        _notify_owner_decision_mm(db, project, new_status, project_name)

    return project


def process_action(db: Session, context: dict, mm_user_id: Optional[str]) -> dict:
    """Обработать нажатие кнопки в карточке Mattermost.

    Возвращает тело ответа для Mattermost (``update`` / ``ephemeral_text``).
    Идентифицирует пользователя по email из Mattermost и применяет ту же
    логику смены статуса — согласовывать по-прежнему могут только CFO/менеджер.
    """
    decision = (context or {}).get("decision")
    new_status = DECISION_TO_STATUS.get(decision)
    if not new_status:
        return {"ephemeral_text": "Неизвестное действие."}

    project_id = (context or {}).get("project_id")
    try:
        project = db.get(Project, int(project_id))
    except (TypeError, ValueError):
        project = None
    if project is None:
        return {"ephemeral_text": "Проект не найден."}

    email = mattermost_service.get_user_email(mm_user_id) if mm_user_id else None
    actor = db.query(User).filter(User.email == email).first() if email else None
    if actor is None:
        return {"ephemeral_text": "Пользователь не распознан в системе."}

    try:
        apply_status_change(db, project, new_status, actor, actor_type="user")
    except HTTPException as exc:
        return {"ephemeral_text": exc.detail}

    label = _DONE_LABELS.get(new_status, new_status)
    return {
        "update": {"message": f"Заявка «{project.name}» {label} ({actor.full_name})."},
        "ephemeral_text": "Готово.",
    }
