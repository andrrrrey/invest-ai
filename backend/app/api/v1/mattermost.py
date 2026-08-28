"""
Приём вопросов из Mattermost для помощника Hermes (режим «вопросы и аналитика»).

Endpoint принимает slash-команду / outgoing webhook Mattermost, проверяет
токен и отвечает по реальным данным через агента Hermes. Ответ по умолчанию
эфемерный (виден только задавшему) — ради конфиденциальности.

Обработка нажатий кнопок согласования (integration actions) добавится на Этапе 3.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ... import settings_store
from ...database import get_db
from ...services import hermes_agent, approval_service

logger = logging.getLogger("hermes.mattermost")

router = APIRouter(prefix="/mattermost", tags=["mattermost"])

_HELP = (
    "Задайте вопрос, например: «статус проекта X», "
    "«какие заявки ждут согласования», «сводка по портфелю»."
)


@router.post("/hermes")
async def hermes_command(request: Request) -> dict:
    """Ответить на вопрос из Mattermost (slash-команда или outgoing webhook)."""
    form = await request.form()
    token = form.get("token")

    expected = settings_store.get_mattermost_command_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Интеграция с Mattermost не настроена (нет токена команды).",
        )
    if token != expected:
        raise HTTPException(status_code=401, detail="Неверный токен Mattermost")

    text = (form.get("text") or "").strip()
    user_name = form.get("user_name") or form.get("user_id") or "mattermost"
    mm_user_id = form.get("user_id")

    if not text:
        return {"response_type": "ephemeral", "text": _HELP}

    from ...services import mattermost_service
    actor_role = mattermost_service.resolve_system_role(mm_user_id)

    try:
        answer = hermes_agent.ask(text, actor_id=str(user_name), actor_role=actor_role)
    except Exception as exc:  # уже залогировано/зааудировано в агенте
        logger.warning("Hermes agent failed for Mattermost request: %s", type(exc).__name__)
        return {
            "response_type": "ephemeral",
            "text": f"Не удалось получить ответ: {exc}",
        }

    return {"response_type": "ephemeral", "text": answer}


@router.post("/actions")
async def hermes_action(request: Request, db: Session = Depends(get_db)) -> dict:
    """Обработать нажатие кнопки в карточке согласования (integration action)."""
    payload = await request.json()
    context = payload.get("context") or {}

    expected = settings_store.get_mattermost_command_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Интеграция с Mattermost не настроена (нет токена команды).",
        )
    if context.get("token") != expected:
        raise HTTPException(status_code=401, detail="Неверный токен Mattermost")

    return approval_service.process_action(db, context, payload.get("user_id"))
