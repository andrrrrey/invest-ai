"""
Реестр MCP-инструментов: единый источник описаний, схем и обработчиков.

Используется и standalone MCP-сервером, и агентом Hermes. ``call_tool``
выполняет операцию под сервис-аккаунтом, изолирует ошибки и пишет аудит
(``action=mcp.tool_call``) — так фиксируется каждое обращение ИИ к данным.
"""

from __future__ import annotations

from typing import Optional

from ..database import SessionLocal
from .. import settings_store
from ..services import audit_service
from . import tools

# Описания и JSON-схемы аргументов (OpenAI/MCP-совместимые).
TOOL_SPECS = [
    {
        "name": "list_projects",
        "description": "Список проектов с краткими показателями. Можно фильтровать по статусу и типу.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "draft | pending_approval | approved | rejected | rework_needed",
                },
                "project_type": {
                    "type": "string",
                    "description": "investment | operational | smart_contract",
                },
            },
        },
        "handler": tools.list_projects,
    },
    {
        "name": "find_projects",
        "description": (
            "Найти проекты по части НАЗВАНИЯ (регистронезависимо). Используй, "
            "когда пользователь называет проект словами, а не числовым id — "
            "возвращает id, статус и ссылку. Затем при необходимости вызови "
            "get_project по найденному id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Часть названия проекта."}
            },
            "required": ["query"],
        },
        "handler": tools.find_projects,
    },
    {
        "name": "get_project",
        "description": "Детали одного проекта: статус, метрики, уровень риска, история статусов.",
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "integer"}},
            "required": ["project_id"],
        },
        "handler": tools.get_project,
    },
    {
        "name": "get_portfolio_stats",
        "description": "Агрегированная сводка по портфелю: счётчики по статусам/типам, суммарный NPV, средний IRR, бюджет.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_type": {
                    "type": "string",
                    "description": "Опционально сузить до типа проектов.",
                }
            },
        },
        "handler": tools.get_portfolio_stats,
    },
    {
        "name": "list_pending_approvals",
        "description": "Проекты, ожидающие согласования (статус pending_approval).",
        "parameters": {"type": "object", "properties": {}},
        "handler": tools.list_pending_approvals,
    },
    {
        "name": "get_project_facts",
        "description": "Фактические показатели проекта: план, факт и отклонение по метрикам.",
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "integer"}},
            "required": ["project_id"],
        },
        "handler": tools.get_project_facts,
    },
    {
        "name": "get_milestones",
        "description": "Майлстоуны смарт-контракта: статус, дедлайн, вознаграждение.",
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "integer"}},
            "required": ["project_id"],
        },
        "handler": tools.get_milestones,
    },
    {
        "name": "list_upcoming_deadlines",
        "description": (
            "Сроки по проектам: незавершённые майлстоуны с приближающимися или "
            "просроченными дедлайнами. Для вопросов про сроки, дедлайны, "
            "просрочки и контроль действующих проектов."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": "Горизонт в днях (по умолчанию 30). Просроченные включаются всегда.",
                }
            },
        },
        "handler": tools.list_upcoming_deadlines,
    },
]

# Инструменты на ЗАПИСЬ — доступны только при hermes_write_enabled (Этап 4).
# Согласование (решения) помощнику недоступно ни при каких настройках.
WRITE_TOOL_SPECS = [
    {
        "name": "update_fact",
        "description": "Обновить фактические/плановые значения по метрикам проекта (рутина заявителя).",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "entries": {
                    "type": "array",
                    "description": "Список записей факта.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "year": {"type": "integer"},
                            "month": {"type": "integer"},
                            "metric_name": {"type": "string"},
                            "plan_value": {"type": "number"},
                            "fact_value": {"type": "number"},
                        },
                        "required": ["year", "month", "metric_name"],
                    },
                },
            },
            "required": ["project_id", "entries"],
        },
        "handler": tools.update_fact,
    },
    {
        "name": "update_milestone_status",
        "description": "Изменить статус майлстоуна смарт-контракта: pending|in_progress|verify|paid|disputed.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "index": {"type": "integer", "description": "Порядковый номер майлстоуна (с 0)."},
                "status": {"type": "string"},
            },
            "required": ["project_id", "index", "status"],
        },
        "handler": tools.update_milestone_status,
    },
]

_BY_NAME = {spec["name"]: spec for spec in TOOL_SPECS}
_WRITE_BY_NAME = {spec["name"]: spec for spec in WRITE_TOOL_SPECS}
_ALL_BY_NAME = {**_BY_NAME, **_WRITE_BY_NAME}


def _spec_to_openai(spec: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec["parameters"],
        },
    }


def openai_tools() -> list:
    """Описания инструментов в формате OpenAI function-calling (для агента).

    Write-инструменты добавляются только когда включён режим записи.
    """
    specs = list(TOOL_SPECS)
    if settings_store.is_hermes_write_enabled():
        specs += WRITE_TOOL_SPECS
    return [_spec_to_openai(spec) for spec in specs]


def call_tool(
    name: str,
    arguments: Optional[dict] = None,
    *,
    actor_type: str = "hermes",
    actor_id: Optional[str] = None,
    db=None,
) -> dict:
    """Выполнить разрешённую операцию по имени. Всегда пишет аудит.

    Аргументы инструментов — это идентификаторы и фильтры (не конфиденциальные
    данные), поэтому безопасно фиксируются в метаданных аудита.
    """
    arguments = arguments or {}
    spec = _ALL_BY_NAME.get(name)
    if spec is None:
        audit_service.log_event(
            action="mcp.tool_call",
            actor_type=actor_type,
            actor_id=actor_id,
            result="error",
            error_message=f"Неизвестный инструмент: {name}",
            target_type="tool",
            target_id=name,
        )
        return {"error": f"Неизвестный инструмент: {name}"}

    # Гейт записи: write-инструменты запрещены, пока не включён режим записи.
    if name in _WRITE_BY_NAME and not settings_store.is_hermes_write_enabled():
        audit_service.log_event(
            action="mcp.tool_call",
            actor_type=actor_type,
            actor_id=actor_id,
            result="error",
            error_message="Режим записи выключен (hermes_write_enabled=false)",
            target_type="tool",
            target_id=name,
        )
        return {"error": "Операции на запись отключены. Включите их в настройках."}

    own_session = db is None
    session = db or SessionLocal()
    try:
        result = spec["handler"](session, **arguments)
        audit_service.log_event(
            action="mcp.tool_call",
            actor_type=actor_type,
            actor_id=actor_id,
            result="ok",
            target_type="tool",
            target_id=name,
            meta={"args": arguments},
        )
        return result
    except Exception as exc:
        audit_service.log_event(
            action="mcp.tool_call",
            actor_type=actor_type,
            actor_id=actor_id,
            result="error",
            error_message=f"{type(exc).__name__}: {exc}",
            target_type="tool",
            target_id=name,
            meta={"args": arguments},
        )
        return {"error": f"Ошибка инструмента {name}: {exc}"}
    finally:
        if own_session:
            session.close()
