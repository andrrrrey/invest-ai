"""
AI service — wraps the Anthropic Claude API for project-level features:
  - generate_description: formulate project description from key fields
  - generate_risks: produce risks & assumptions analysis
  - analyze_project: detect anomalies, compare with portfolio median
"""

from typing import Optional
import anthropic

from ..config import settings


def _client() -> anthropic.Anthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


SYSTEM_PROMPT = (
    "Ты — Ксения, AI-ассистент инвестиционного процессора. "
    "Отвечай строго по-русски, лаконично и профессионально. "
    "Используй финансовую терминологию. "
    "Не добавляй вводных фраз вроде «Конечно!» или «С удовольствием помогу»."
)


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
    client = _client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def generate_risks(
    project_name: str,
    metrics: dict,
    financial_model: dict,
) -> dict:
    """
    Generate risks and assumptions based on financial model data.
    Returns {"risks": [...], "assumptions": "...", "ai_assessment": {...}}
    """
    npv = metrics.get("npv", 0)
    irr = metrics.get("irr", "н/д")
    ltv_cac = metrics.get("ltvCac", 0)
    dpp = metrics.get("dpp", "н/д")
    avg_churn = metrics.get("avgChurn", 0)

    prompt = (
        f"Проанализируй инвестиционный проект «{project_name}».\n"
        f"Ключевые метрики:\n"
        f"  NPV: {npv:,.0f} ₽\n"
        f"  IRR: {irr}%\n"
        f"  LTV/CAC: {ltv_cac}\n"
        f"  DPP: {dpp} лет\n"
        f"  Средний квартальный отток: {avg_churn}%\n"
        f"  Модель выручки: {financial_model.get('revenueModel', 'н/д')}\n\n"
        "Верни JSON со следующей структурой (только JSON, без Markdown):\n"
        "{\n"
        '  "risks": ["Технические: ...", "Рыночные: ...", "Операционные: ...", "Финансовые: ..."],\n'
        '  "assumptions": "Текст 2-3 предложения о ключевых допущениях",\n'
        '  "ai_assessment": {\n'
        '    "risk_level": "низкий|средний|высокий",\n'
        '    "recommendation": "Текст рекомендации",\n'
        '    "weaknesses": ["слабое место 1", "слабое место 2"]\n'
        "  }\n"
        "}"
    )

    client = _client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = message.content[0].text.strip()
    # Strip potential markdown code fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "risks": ["Ошибка парсинга ответа AI"],
            "assumptions": text,
            "ai_assessment": {"risk_level": "средний", "recommendation": "", "weaknesses": []},
        }


def analyze_project(project: dict, metrics: dict) -> dict:
    """
    Analyze anomalies and give AI commentary for project detail page.
    """
    prompt = (
        f"Проект «{project.get('name', '?')}» (статус: {project.get('status', '?')}).\n"
        f"NPV: {metrics.get('npv', 0):,.0f} ₽, IRR: {metrics.get('irr', 'н/д')}%, "
        f"LTV/CAC: {metrics.get('ltvCac', 0)}, DPP: {metrics.get('dpp', 'н/д')} лет.\n\n"
        "Верни JSON (только JSON, без Markdown):\n"
        "{\n"
        '  "comment": "Краткий AI-комментарий 1-2 предложения",\n'
        '  "anomalies": ["Аномалия 1 если есть", ...],\n'
        '  "comparison": "Сравнение с похожими проектами"\n'
        "}"
    )
    client = _client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"comment": text, "anomalies": [], "comparison": ""}
