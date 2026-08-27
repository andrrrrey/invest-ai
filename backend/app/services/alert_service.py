"""
Оповещения об ошибках в служебный канал Mattermost.

При ошибке (например сбой вызова ИИ) отправляется сообщение во входящий
webhook Mattermost, чтобы реагировать сразу, не дожидаясь жалоб пользователей.
На Этапе 1 достаточно incoming webhook — бот не требуется.

В текст оповещения НЕ должны попадать конфиденциальные данные: передавайте
только провайдера/модель, тип ошибки и безопасные метаданные.
"""

from __future__ import annotations

import logging

import httpx

from .. import settings_store

logger = logging.getLogger("hermes.alert")


def send_alert(text: str) -> bool:
    """Отправить оповещение в служебный канал. Возвращает True при успехе.

    Никогда не поднимает исключение — сбой доставки алерта не должен ломать
    основную операцию.
    """
    webhook = settings_store.get_mattermost_alert_webhook()
    if not webhook:
        logger.warning(
            "Служебный webhook Mattermost не настроен — оповещение не отправлено",
            extra={"event": {"alert_dropped": True}},
        )
        return False
    try:
        resp = httpx.post(
            webhook,
            json={"text": f":rotating_light: [Hermes] {text}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("Не удалось отправить оповещение в Mattermost")
        return False
