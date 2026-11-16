"""Шлюз для ВНЕШНИХ MCP-клиентов: обезличивание + единая точка вызова.

Используется обоими транспортами standalone-сервера (stdio и HTTP, см.
``app.mcp.server``). Внутренний агент Hermes сюда не ходит — у него своё
обезличивание на время диалога (``services.hermes_agent``).

Почему отдельный обезличиватель
-------------------------------
Агент Hermes нумерует метки в пределах одного диалога (``[PROJECT_1]``). У
внешнего клиента «диалог» нам не виден: каждый вызов инструмента — отдельный
запрос, а модель на стороне клиента запоминает метки и передаёт их обратно в
аргументах (``find_projects(query="[PROJECT_7F3A2C1B]")``). Поэтому метки здесь
**стабильные**: ``[КАТЕГОРИЯ_<HMAC>]``, где HMAC считается от значения на
``SECRET_KEY``. Одно и то же значение всегда даёт одну и ту же метку — между
вызовами, сессиями и перезапусками сервера, а без ключа метку нельзя
сопоставить со значением перебором.

Обратное сопоставление «метка → значение» хранится в памяти процесса и перед
каждым вызовом пополняется всеми известными чувствительными значениями из БД,
поэтому метки проектов/ФИО/МВЗ восстанавливаются и после перезапуска.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from typing import Any, Dict, List, Optional

from ..config import settings
from ..database import SessionLocal
from ..services import anonymizer
from .. import settings_store
from . import registry

_CATEGORIES = ("project", "person", "mvz", "contact", "org")


class StableAnonymizer(anonymizer.Anonymizer):
    """Обезличиватель со стабильными (детерминированными) метками."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = (secret or "").encode("utf-8")

    def _register(self, original: str, category: str) -> str:
        if original in self._seen:
            return self._seen[original]
        prefix = anonymizer.CATEGORY_PREFIX.get(category, "TERM")
        digest = hmac.new(
            self._secret, f"{category}:{original}".encode("utf-8"), hashlib.sha256
        ).hexdigest().upper()
        # 8 hex-символов достаточно; при (крайне редкой) коллизии удлиняем.
        length = 8
        placeholder = f"[{prefix}_{digest[:length]}]"
        while self.mapping.get(placeholder, original) != original and length < len(digest):
            length += 4
            placeholder = f"[{prefix}_{digest[:length]}]"
        self.mapping[placeholder] = original
        self._seen[original] = placeholder
        return placeholder

    def prime(self, terms: Dict[str, List[str]]) -> None:
        """Зарегистрировать метки для всех известных значений (для unmask)."""
        for category, values in (terms or {}).items():
            for value in values or []:
                if isinstance(value, str) and value.strip():
                    self._register(value.strip(), category)

    def unmask_obj(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unmask_obj(v) for v in obj]
        if isinstance(obj, str):
            return self.unmask(obj)
        return obj


_lock = threading.Lock()
_anonymizer: Optional[StableAnonymizer] = None


def _get_anonymizer() -> StableAnonymizer:
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = StableAnonymizer(settings.SECRET_KEY)
    return _anonymizer


def _reset_anonymizer() -> None:
    """Для тестов: сбросить накопленное сопоставление."""
    global _anonymizer
    with _lock:
        _anonymizer = None


def sensitive_terms(db) -> Dict[str, List[str]]:
    """Чувствительные значения для обезличивания ответа внешнему клиенту.

    Всё, что маскирует агент Hermes (названия проектов, бизнес-юниты,
    владельцы, кураторы и команды, коды МВЗ), плюс ФИО пользователей системы —
    они встречаются в комментариях, истории статусов и аудите. Имена из одного
    слова («CFO», «CEO» у служебных аккаунтов) не берём, чтобы не портить
    обычный текст.
    """
    from ..models.user import User
    from ..services.hermes_agent import _global_sensitive_terms

    terms = _global_sensitive_terms(db)
    for c in _CATEGORIES:
        terms.setdefault(c, [])
    for (full_name,) in db.query(User.full_name).all():
        name = (full_name or "").strip()
        if len(name.split()) >= 2 and name not in terms["person"]:
            terms["person"].append(name)
    return terms


def list_tool_specs() -> list:
    """Инструменты, которые видит внешний клиент: только чтение.

    Write-инструменты внешнему серверу не отдаются при любых настройках;
    ``search_knowledge`` — только при включённой базе знаний.
    """
    specs = list(registry.TOOL_SPECS)
    if not settings_store.is_knowledge_enabled():
        specs = [s for s in specs if s["name"] != "search_knowledge"]
    return specs


def call_external_tool(
    name: str,
    arguments: Optional[dict] = None,
    *,
    actor_id: Optional[str] = None,
) -> Any:
    """Выполнить инструмент по запросу внешнего клиента.

    - разрешены только read-only инструменты из :func:`list_tool_specs`;
    - при включённом ``mcp_anonymize_enabled`` метки в аргументах
      восстанавливаются перед выполнением, а результат обезличивается;
    - в аудит (``actor_type=ai_gateway``) пишутся аргументы в том виде, в
      каком их прислал клиент (т.е. обезличенные).
    """
    arguments = dict(arguments or {})
    allowed = {s["name"] for s in list_tool_specs()}
    if name not in allowed:
        if name not in registry._ALL_BY_NAME:
            # Неизвестное имя: registry вернёт ошибку и сам запишет аудит.
            return registry.call_tool(name, arguments, actor_type="ai_gateway", actor_id=actor_id)
        # Write-инструменты (и выключенная база знаний) внешним клиентам недоступны.
        from ..services import audit_service

        message = f"Инструмент {name} недоступен внешним MCP-клиентам"
        audit_service.log_event(
            action="mcp.tool_call",
            actor_type="ai_gateway",
            actor_id=actor_id,
            result="error",
            error_message=message,
            target_type="tool",
            target_id=name,
        )
        return {"error": message}

    if not settings_store.is_mcp_anonymize_enabled():
        return registry.call_tool(name, arguments, actor_type="ai_gateway", actor_id=actor_id)

    db = SessionLocal()
    try:
        terms = sensitive_terms(db)
        with _lock:
            az = _get_anonymizer()
            az.prime(terms)
            exec_args = az.unmask_obj(arguments)
        result = registry.call_tool(
            name,
            exec_args,
            actor_type="ai_gateway",
            actor_id=actor_id,
            db=db,
            audit_arguments=arguments,
            anonymized=True,
        )
        with _lock:
            return az.mask_obj(result, terms)
    finally:
        db.close()


SERVER_INSTRUCTIONS = (
    "Инвестиционный процессор: инструменты только для чтения (проекты, портфель, "
    "сроки, факт, риски, бюджет, база знаний). Ответы могут быть обезличены: "
    "названия проектов, ФИО, бизнес-юниты, коды МВЗ и контакты заменены метками "
    "вида [PROJECT_1A2B3C4D], [PERSON_…], [ORG_…], [MVZ_…], [CONTACT_…]. Метки "
    "стабильны — одна и та же метка всегда означает одно и то же значение; их "
    "можно передавать в аргументы инструментов как есть (например, "
    "find_projects(query=\"[PROJECT_1A2B3C4D]\")). Не пытайся угадать исходные "
    "значения. Поле url ведёт на карточку проекта в системе."
)
