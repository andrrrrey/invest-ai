"""Тесты единой точки ИИ: обезличивание на выходе, аудит, оповещение об ошибке."""

import pytest

from app import settings_store
from app.database import SessionLocal
from app.models.audit_log import AuditLog
from app.services import ai_service


def _latest_audit() -> AuditLog:
    session = SessionLocal()
    try:
        return session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    finally:
        session.close()


def test_chat_masks_outbound_restores_inbound_and_audits(monkeypatch):
    captured = {}

    def fake_dispatch(provider, prompt, max_tokens):
        captured["prompt"] = prompt
        return prompt  # эхо: возвращаем обезличенный текст как "ответ ИИ"

    monkeypatch.setattr(ai_service, "_dispatch", fake_dispatch)
    monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "routerai")
    monkeypatch.setattr(settings_store, "get_routerai_model", lambda: "anthropic/claude-sonnet-4.5")
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: True)

    out = ai_service._chat("Проект «Тайный Проект» контакт boss@example.com")

    # Во внешний ИИ ушёл обезличенный текст.
    assert "Тайный Проект" not in captured["prompt"]
    assert "boss@example.com" not in captured["prompt"]
    assert "[PROJECT_1]" in captured["prompt"]

    # Пользователю вернулся текст с восстановленными значениями.
    assert "Тайный Проект" in out
    assert "boss@example.com" in out

    # Аудит зафиксирован, обезличивание подтверждено, сырого текста в записи нет.
    row = _latest_audit()
    assert row is not None
    assert row.action == "ai.chat"
    assert row.result == "ok"
    assert row.anonymized is True
    assert row.ai_provider == "routerai"
    assert row.ai_model == "anthropic/claude-sonnet-4.5"
    assert "Тайный Проект" not in (row.error_message or "")
    assert row.meta.get("entities_masked") >= 1


def test_chat_error_is_audited_and_alerts(monkeypatch):
    alerts = []

    def boom(provider, prompt, max_tokens):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai_service, "_dispatch", boom)
    monkeypatch.setattr(ai_service.alert_service, "send_alert", lambda text: alerts.append(text) or True)
    monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "openai")
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: True)

    with pytest.raises(RuntimeError):
        ai_service._chat("Проект «Икс»")

    # Оповещение отправлено, ошибка зафиксирована в аудите.
    assert alerts, "оповещение об ошибке должно быть отправлено"
    row = _latest_audit()
    assert row.result == "error"
    assert row.action == "ai.chat"
    # В журнал не должен попасть исходный конфиденциальный текст.
    assert "Икс" not in (row.error_message or "")
