"""
AI service — wraps the OpenAI API (GPT-4o) for project-level features:
  - generate_description: formulate project description from key fields
  - generate_risks: produce risks & assumptions analysis
  - analyze_project: detect anomalies, compare with portfolio median
"""

import json
from typing import Optional
from openai import OpenAI

from ..config import settings


SYSTEM_PROMPT = (
    "Ты — Ксения, AI-ассистент инвестиционного процессора. "
    "Отвечай строго по-русски, лаконично и профессионально. "
    "Используй финансовую терминологию. "
    "Не добавляй вводных фраз вроде «Конечно!» или «С удовольствием помогу»."
)


def _client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat(prompt: str, max_tokens: int = 700) -> str:
    response = _client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def generate_description(
    project_name: str,
    business_unit: str,
    project_type: str,
    stage: Optional[str] = None,
) -> str:
    """Generate a 2-3 paragraph project description."""
    prompt = (
        f"Сформулируй краткое описание (2-3 абзаца) инвестиционного проекта:\n"
        f"— Название: {project_name}\n"
        f"— Тип: {project_type}\n"
        f"— Бизнес-юнит: {business_unit}\n"
        f"— Стадия: {stage or 'не указана'}\n\n"
        "Опиши суть проекта, ключевой бизнес-эффект и целевую аудиторию."
    )
    return _chat(prompt, max_tokens=600)


def generate_risks(project_name: str, metrics: dict, financial_model: dict) -> dict:
    """
    Generate risks and assumptions based on financial model data.
    Returns {"risks": [...], "assumptions": "...", "ai_assessment": {...}}
    """
    prompt = (
        f"Проанализируй инвестиционный проект «{project_name}».\n"
        f"Ключевые метрики:\n"
        f"  NPV: {metrics.get('npv', 0):,.0f} ₽\n"
        f"  IRR: {metrics.get('irr', 'н/д')}%\n"
        f"  LTV/CAC: {metrics.get('ltvCac', 0)}\n"
        f"  DPP: {metrics.get('dpp', 'н/д')} лет\n"
        f"  Средний квартальный отток: {metrics.get('avgChurn', 0)}%\n"
        f"  Модель выручки: {financial_model.get('revenueModel', 'н/д')}\n\n"
        "Верни JSON (только JSON, без Markdown):\n"
        '{"risks": ["Технические: ...", "Рыночные: ...", "Операционные: ...", "Финансовые: ..."],'
        '"assumptions": "2-3 предложения о ключевых допущениях",'
        '"ai_assessment": {"risk_level": "низкий|средний|высокий",'
        '"recommendation": "текст", "weaknesses": ["слабое место 1", "слабое место 2"]}}'
    )
    text = _strip_fences(_chat(prompt, max_tokens=900))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "risks": ["Ошибка парсинга ответа AI"],
            "assumptions": text,
            "ai_assessment": {"risk_level": "средний", "recommendation": "", "weaknesses": []},
        }


def analyze_project(project: dict, metrics: dict) -> dict:
    """Analyze anomalies and give AI commentary for project detail page."""
    prompt = (
        f"Проект «{project.get('name', '?')}» (статус: {project.get('status', '?')}).\n"
        f"NPV: {metrics.get('npv', 0):,.0f} ₽, IRR: {metrics.get('irr', 'н/д')}%, "
        f"LTV/CAC: {metrics.get('ltvCac', 0)}, DPP: {metrics.get('dpp', 'н/д')} лет.\n\n"
        "Верни JSON (только JSON, без Markdown):\n"
        '{"comment": "1-2 предложения", "anomalies": ["аномалия если есть"], "comparison": "сравнение с похожими"}'
    )
    text = _strip_fences(_chat(prompt, max_tokens=400))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"comment": text, "anomalies": [], "comparison": ""}
