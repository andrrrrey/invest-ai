"""
Сервис аудита — единая точка записи событий в журнал ``audit_log``.

Пишет и в структурный лог (JSON), и в БД. Конфиденциальные данные сюда не
передаются: только метаданные, метки и безопасные счётчики. Запись в БД
обёрнута в try/except, поэтому сбой журналирования никогда не ломает основную
операцию (вызов ИИ, действие помощника).

Может вызываться как из запроса (с переданной сессией ``db``), так и из
фонового/не-HTTP контекста (MCP-сервер, агент) — тогда открывает собственную
короткоживущую сессию.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..database import SessionLocal

logger = logging.getLogger("hermes.audit")


def log_event(
    *,
    action: str,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    result: str = "ok",
    error_message: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    ai_provider: Optional[str] = None,
    ai_model: Optional[str] = None,
    anonymized: bool = False,
    meta: Optional[dict] = None,
    db=None,
) -> None:
    """Записать событие в структурный лог и в таблицу аудита."""
    event = {
        "action": action,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "result": result,
        "target_type": target_type,
        "target_id": target_id,
        "ai_provider": ai_provider,
        "ai_model": ai_model,
        "anonymized": anonymized,
        "meta": meta,
    }
    if error_message:
        # Усечём и не даём протечь потенциально длинному тексту в лог.
        event["error"] = error_message[:500]
    log_fn = logger.error if result == "error" else logger.info
    log_fn("audit", extra={"event": event})

    # Персист в БД (изолированно от структурного лога).
    from ..models.audit_log import AuditLog  # локальный импорт против циклов

    own_session = db is None
    session = db or SessionLocal()
    try:
        entry = AuditLog(
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            result=result,
            error_message=error_message[:2000] if error_message else None,
            ai_provider=ai_provider,
            ai_model=ai_model,
            anonymized=anonymized,
            meta=meta,
        )
        session.add(entry)
        if own_session:
            session.commit()
    except Exception:
        logger.exception("Не удалось сохранить запись аудита")
        if own_session:
            try:
                session.rollback()
            except Exception:
                pass
    finally:
        if own_session:
            session.close()
