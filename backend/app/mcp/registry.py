"""
Реестр MCP-инструментов: единый источник описаний, схем и обработчиков.

Используется и standalone MCP-сервером, и агентом Hermes. ``call_tool``
выполняет операцию под сервис-аккаунтом, изолирует ошибки и пишет аудит
(``action=mcp.tool_call``) — так фиксируется каждое обращение ИИ к данным.
"""

from __future__ import annotations

from typing import Optional

from ..database import SessionLocal
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
]

_BY_NAME = {spec["name"]: spec for spec in TOOL_SPECS}


def openai_tools() -> list:
    """Описания инструментов в формате OpenAI function-calling (для агента)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in TOOL_SPECS
    ]


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
    spec = _BY_NAME.get(name)
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
