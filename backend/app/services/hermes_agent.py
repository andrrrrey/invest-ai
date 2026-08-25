"""
Агент Hermes — режим «вопросы и аналитика».

Агентный цикл tool-calling на RouterAI (Claude) / OpenAI-совместимом API.
Помощник отвечает на вопросы по РЕАЛЬНЫМ данным, но только через разрешённые
MCP-инструменты (``app.mcp.registry``) — прямого доступа к базе у ИИ нет.

Конфиденциальность: вопрос пользователя и результаты инструментов
обезличиваются ОДНИМ общим обезличивателем (согласованные метки в пределах
диалога) перед отправкой во внешний ИИ, а финальный ответ восстанавливается
обратно. Каждый ответ фиксируется в аудите.

Роли и порядок согласования не меняются: Hermes не принимает решения за людей.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI

from .. import settings_store
from ..database import SessionLocal
from ..models.project import Project
from ..mcp import registry
from . import ai_service, alert_service, audit_service, anonymizer

logger = logging.getLogger("hermes.agent")

SYSTEM_PROMPT = (
    "Ты — Hermes, AI-ассистент инвестиционного процессора. "
    "Отвечай строго по-русски, лаконично и профессионально, опираясь ТОЛЬКО на "
    "данные, полученные через инструменты. Не выдумывай факты и цифры: если "
    "данных нет — так и скажи. Для ответа используй подходящие инструменты "
    "(список проектов, детали проекта, сводка портфеля, заявки на согласование, "
    "факт по проекту, майлстоуны). "
    "Ты не принимаешь решения за людей и не меняешь статусы — только помогаешь "
    "информацией и аналитикой. Роли и порядок согласования (CFO и менеджер "
    "согласуют, CEO наблюдает) неизменны."
)

_MAX_TOOL_CONTENT = 6000  # символов на один результат инструмента


def _project_to_dict(p: Project) -> dict:
    return {
        "name": p.name,
        "business_unit": p.business_unit,
        "owner": p.owner,
        "smart_contract_data": p.smart_contract_data,
        "financial_model": p.financial_model,
    }


def _global_sensitive_terms(db) -> dict:
    """Собрать чувствительные значения по всем проектам для согласованного
    обезличивания вопроса и результатов инструментов."""
    merged = {"project": [], "person": [], "mvz": [], "contact": [], "org": []}
    for p in db.query(Project).all():
        terms = anonymizer.collect_project_terms(_project_to_dict(p))
        for key in merged:
            merged[key].extend(terms.get(key, []))
    return {key: list(dict.fromkeys(vals)) for key, vals in merged.items()}


def _client_and_model():
    provider = settings_store.get_ai_provider()
    if provider == "routerai":
        key = settings_store.get_routerai_key()
        if not key:
            raise ValueError("RouterAI API ключ не настроен. Откройте Настройки и введите ключ.")
        return OpenAI(api_key=key, base_url=ai_service.ROUTERAI_BASE_URL), settings_store.get_routerai_model(), provider
    if provider == "openai":
        key = settings_store.get_openai_key()
        if not key:
            raise ValueError("OpenAI API ключ не настроен. Откройте Настройки и введите ключ.")
        return OpenAI(api_key=key), ai_service.OPENAI_MODEL, provider
    raise ValueError(
        f"Агент Hermes поддерживает провайдеры openai/routerai (текущий: {provider}). "
        "Переключите провайдера в настройках."
    )


def ask(question: str, *, actor_id: Optional[str] = None, max_steps: int = 5) -> str:
    """Ответить на вопрос пользователя по реальным данным через инструменты."""
    if not settings_store.is_ai_enabled():
        raise ValueError(
            "AI-функции отключены. Включите их в Настройках (передача данных во "
            "внешние AI-провайдеры разрешается ответственным лицом)."
        )

    client, model, provider = _client_and_model()
    anonymize_on = settings_store.is_anonymize_enabled()
    az = anonymizer.Anonymizer()

    db = SessionLocal()
    try:
        terms = _global_sensitive_terms(db) if anonymize_on else None
    finally:
        db.close()

    def _mask(text: str) -> str:
        return az.mask(text, terms) if anonymize_on else text

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _mask(question)},
    ]
    tools = registry.openai_tools()
    steps = 0

    try:
        for steps in range(1, max_steps + 1):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=900,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                answer = az.unmask(msg.content or "") if anonymize_on else (msg.content or "")
                audit_service.log_event(
                    action="hermes.answer",
                    actor_type="hermes",
                    actor_id=actor_id,
                    result="ok",
                    ai_provider=provider,
                    ai_model=model,
                    anonymized=anonymize_on,
                    meta={"steps": steps, "entities_masked": len(az.mapping)},
                )
                return answer.strip()

            # Модель запросила инструменты — выполняем и возвращаем результаты.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = registry.call_tool(
                    tc.function.name, args, actor_type="hermes", actor_id=actor_id
                )
                raw = json.dumps(result, ensure_ascii=False, default=str)[:_MAX_TOOL_CONTENT]
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _mask(raw),
                    }
                )

        # Лимит шагов исчерпан.
        audit_service.log_event(
            action="hermes.answer",
            actor_type="hermes",
            actor_id=actor_id,
            result="error",
            error_message="Достигнут лимит шагов агента",
            ai_provider=provider,
            ai_model=model,
            anonymized=anonymize_on,
            meta={"steps": steps},
        )
        return "Не удалось сформировать ответ за отведённое число шагов. Уточните вопрос."
    except Exception as exc:
        audit_service.log_event(
            action="hermes.answer",
            actor_type="hermes",
            actor_id=actor_id,
            result="error",
            error_message=f"{type(exc).__name__}: {exc}",
            ai_provider=provider,
            ai_model=model,
            anonymized=anonymize_on,
            meta={"steps": steps},
        )
        alert_service.send_alert(
            f"Ошибка агента Hermes ({provider}/{model}): {type(exc).__name__}: {exc}"
        )
        raise
