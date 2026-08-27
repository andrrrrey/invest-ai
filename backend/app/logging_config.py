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
    """Настроить корневой логгер и логгеры uvicorn на JSON-вывод."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JSONFormatter}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
            },
        }
    )
