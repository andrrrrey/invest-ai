"""
Клиент бота Mattermost.

Отправляет личные сообщения (DM) пользователям по email и интерактивные
карточки согласования с кнопками «Согласовать / Отклонить / На доработку».
Все вызовы «мягкие»: если бот не настроен или API недоступен — функции пишут
предупреждение и возвращают False, не ломая основную операцию.

ВАЖНО: Mattermost — внутренняя доверенная система, поэтому реальные названия и
ФИО отправляются как есть. Обезличивание применяется только для ВНЕШНЕГО ИИ.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from .. import settings_store

logger = logging.getLogger("hermes.mattermost")

_TIMEOUT = 6.0


def is_configured() -> bool:
    return bool(
        settings_store.get_mattermost_bot_token()
        and settings_store.get_mattermost_base_url()
    )


def mattermost_email(user) -> Optional[str]:
    """Email для поиска пользователя в Mattermost.

    Возвращает специальное поле ``mattermost_email`` (если задано), иначе —
    основной email. Нужно, когда email в Mattermost отличается от email в системе.
    """
    if user is None:
        return None
    return (getattr(user, "mattermost_email", None) or getattr(user, "email", None)) or None


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings_store.get_mattermost_bot_token()}"}


def _base() -> str:
    return (settings_store.get_mattermost_base_url() or "").rstrip("/")


def get_user_id_by_email(email: str) -> Optional[str]:
    if not is_configured() or not email:
        return None
    try:
        r = httpx.get(f"{_base()}/api/v4/users/email/{email}", headers=_headers(), timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("id")
    except Exception:
        logger.exception("Mattermost: не удалось найти пользователя по email")
    return None


def get_user_email(user_id: str) -> Optional[str]:
    """Определить email пользователя Mattermost (для сопоставления с аккаунтом)."""
    if not is_configured() or not user_id:
        return None
    try:
        r = httpx.get(f"{_base()}/api/v4/users/{user_id}", headers=_headers(), timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("email")
    except Exception:
        logger.exception("Mattermost: не удалось получить email пользователя")
    return None


def post_to_email(email: str, message: str, attachments: Optional[list] = None) -> bool:
    """Отправить личное сообщение пользователю по его email."""
    if not is_configured():
        logger.warning("Mattermost не настроен — сообщение не отправлено")
        return False
    try:
        me = httpx.get(f"{_base()}/api/v4/users/me", headers=_headers(), timeout=_TIMEOUT).json()
        target_id = get_user_id_by_email(email)
        if not target_id:
            logger.warning("Mattermost: получатель %s не найден", email)
            return False
        ch = httpx.post(
            f"{_base()}/api/v4/channels/direct",
            headers=_headers(),
            json=[me["id"], target_id],
            timeout=_TIMEOUT,
        ).json()
        payload = {"channel_id": ch["id"], "message": message}
        if attachments:
            payload["props"] = {"attachments": attachments}
        r = httpx.post(f"{_base()}/api/v4/posts", headers=_headers(), json=payload, timeout=_TIMEOUT)
        return r.status_code in (200, 201)
    except Exception:
        logger.exception("Mattermost: не удалось отправить сообщение")
        return False


def _approval_card(project_id: int, project_name: str, applicant_name: str) -> dict:
    """Собрать attachment с кнопками решения (integration actions)."""
    token = settings_store.get_mattermost_command_token() or ""
    base = (settings_store.get_mattermost_integration_url() or "").rstrip("/")
    action_url = f"{base}/api/v1/mattermost/actions"

    def _action(action_id: str, name: str, style: str, decision: str) -> dict:
        return {
            "id": action_id,
            "name": name,
            "style": style,
            "integration": {
                "url": action_url,
                "context": {
                    "project_id": project_id,
                    "decision": decision,
                    "token": token,
                },
            },
        }

    return {
        "fallback": f"Заявка на согласование: {project_name}",
        "color": "#2f81f7",
        "title": f"Заявка на согласование: {project_name}",
        "text": f"Заявитель: {applicant_name}\nВыберите решение:",
        "actions": [
            _action("approve", "Согласовать", "good", "approve"),
            _action("reject", "Отклонить", "danger", "reject"),
            _action("rework", "На доработку", "default", "rework"),
        ],
    }


def send_approval_card(
    project_id: int,
    project_name: str,
    applicant_name: str,
    approver_emails: List[str],
) -> int:
    """Отправить карточку согласования всем ответственным. Возвращает число
    успешных отправок."""
    if not is_configured():
        logger.warning("Mattermost не настроен — карточка согласования не отправлена")
        return 0
    attachment = _approval_card(project_id, project_name, applicant_name)
    sent = 0
    for email in approver_emails:
        if post_to_email(email, "Новая заявка на согласование", attachments=[attachment]):
            sent += 1
    return sent
