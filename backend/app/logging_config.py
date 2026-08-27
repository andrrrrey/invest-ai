"""
Структурное (JSON) логирование для сквозного аудита.

Каждая запись — одна JSON-строка со стандартными полями и, при наличии,
объектом ``event`` (безопасные метаданные события). Конфиденциальные данные
в логи не пишутся — за это отвечают вызывающие модули (anonymizer/audit).
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Форматтер, сериализующий запись лога (и extra-поле ``event``) в JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Дополнительные структурированные поля, если их передали через extra=.
        for key in ("event", "audit", "request"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Настроить корневой логгер и логгеры uvicorn на JSON-вывод.

    Логи пишутся и в stdout (для `docker compose logs`), и в ротируемый файл
    ``LOG_FILE`` на постоянном volume — оттуда бэкенд отдаёт их на экране
    «Аудит» (скачивание/отправка разработчику).
    """
    handlers = {
        "default": {"class": "logging.StreamHandler", "formatter": "json"},
    }
    handler_names = ["default"]

    log_file = os.environ.get("LOG_FILE", "/data/logs/app.log")
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "json",
                "filename": log_file,
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            }
            handler_names.append("file")
        except Exception:
            # Файл логов недоступен (нет прав/каталога) — не мешаем старту,
            # остаёмся на stdout.
            pass

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JSONFormatter}},
            "handlers": handlers,
            "root": {"handlers": handler_names, "level": level},
            "loggers": {
                "uvicorn": {"handlers": handler_names, "level": level, "propagate": False},
                "uvicorn.error": {"handlers": handler_names, "level": level, "propagate": False},
                "uvicorn.access": {"handlers": handler_names, "level": level, "propagate": False},
            },
        }
    )
