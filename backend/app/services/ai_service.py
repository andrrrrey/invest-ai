"""
AI service — wraps the OpenAI API (GPT-4.1) for project-level features:
  - generate_description: formulate project description from key fields
  - generate_risks: produce risks & assumptions analysis
  - generate_risk_score: AI risk scoring for operational projects
  - analyze_project: detect anomalies, compare with portfolio median
"""

import json
from typing import Optional
from openai import OpenAI

from .. import settings_store


AI_MODEL = "gpt-4.1"

SYSTEM_PROMPT = (
    "Ты — Ксения, AI-ассистент инвестиционного процессора. "
    "Отвечай строго по-русски, лаконично и профессионально. "
    "Используй финансовую терминологию. "
    "Не добавляй вводных фраз вроде «Конечно!» или «С удовольствием помогу»."
)


def _client() -> OpenAI:
    key = settings_store.get_openai_key()
    if not key:
        raise ValueError(
            "OpenAI API ключ не настроен. Откройте Настройки и введите ключ."
        )
    return OpenAI(api_key=key)


def _chat(prompt: str, max_tokens: int = 700) -> str:
    response = _client().chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=max_tokens,
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


def generate_risk_score(application: dict) -> dict:
    """
    Generate AI Risk Score for a type 1.2 operational investment request.
    Returns risk levels, recommendations, routing suggestion, and manual review flag.
    """
    vs = application.get("value_score_data", {}) or {}
    prompt = (
        f"Ты — AI-инвестиционный процессор. Оцени риски операционной инвестиционной заявки.\n\n"
        f"Инициатива: {application.get('name', 'не указана')}\n"
        f"Категория: {application.get('op_category', '—')}\n"
        f"МВЗ: {application.get('op_mvz_main', '—')} / {application.get('op_mvz_sub1', '—')} / {application.get('op_mvz_sub2', '—')}\n"
        f"Тип инвестиции: {application.get('op_investment_type', '—')}\n"
        f"Запрашиваемый ресурс: {application.get('op_requested_resource', '—')}\n"
        f"Инвестиционный тезис: {application.get('op_investment_thesis', '—')}\n"
        f"Value drivers: {application.get('op_value_drivers', [])}\n"
        f"Метрики: {application.get('op_metrics', '—')}\n"
        f"Baseline: {application.get('op_baseline', '—')}\n"
        f"Target: {application.get('op_target', '—')}\n"
        f"Экономика/Payback: {application.get('op_economics', '—')}\n"
        f"Stop-loss критерии: {application.get('op_stop_loss', '—')}\n"
        f"Stage-gates: {application.get('op_stage_gates', '—')}\n\n"
        f"Value Score: {vs.get('total', '—')} / 50 (зона: {vs.get('band', '—')})\n"
        f"  - Влияние на EV (x3): {vs.get('ev_impact', '—')}\n"
        f"  - Срочность (x2): {vs.get('urgency', '—')}\n"
        f"  - Прогнозируемость ROI (x1): {vs.get('roi_predictability', '—')}\n"
        f"  - Масштабируемость (x2): {vs.get('scalability', '—')}\n"
        f"  - Unit-экономика (x2): {vs.get('unit_economics', '—')}\n\n"
        "Верни строго JSON (только JSON, без Markdown):\n"
        '{"overall_risk": "низкий|умеренный|высокий",'
        '"risk_scores": {"execution_risk": 1-5, "market_risk": 1-5, "financial_risk": 1-5, "strategic_risk": 1-5},'
        '"risk_reasons": ["причина 1", "причина 2", "причина 3"],'
        '"controls": ["контроль 1", "контроль 2"],'
        '"stage_gate_recommendations": ["критерий 1", "критерий 2"],'
        '"recommended_route": "fast_track|efficiency_play|backlog_stop",'
        '"manual_review_required": true|false,'
        '"commentary": "2-3 предложения с ключевым выводом"}\n\n'
        "ВАЖНЫЕ ПРАВИЛА ДЛЯ manual_review_required:\n"
        "- Устанавливай manual_review_required: TRUE только для ПОГРАНИЧНЫХ или СЛОЖНЫХ случаев: "
        "умеренный риск, неоднозначные метрики, нетипичная ситуация, требующая экспертного суждения.\n"
        "- Устанавливай manual_review_required: FALSE для ОЧЕВИДНО НЕПОДХОДЯЩИХ проектов: "
        "все risk_scores >= 4, очень низкий Value Score (< 15), отсутствие экономики, "
        "явная нежизнеспособность. Такие проекты получают recommended_route: 'backlog_stop' автоматически.\n"
        "- Устанавливай manual_review_required: FALSE и для ЯВНО ХОРОШИХ проектов (fast_track/efficiency_play).\n"
        "- recommended_route должен быть одним из: fast_track, efficiency_play, backlog_stop "
        "(НЕ используй 'manual_review' в качестве маршрута)."
    )
    text = _strip_fences(_chat(prompt, max_tokens=1000))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "overall_risk": "умеренный",
            "risk_scores": {"execution_risk": 3, "market_risk": 3, "financial_risk": 3, "strategic_risk": 3},
            "risk_reasons": ["Ошибка парсинга ответа AI"],
            "controls": [],
            "stage_gate_recommendations": [],
            "recommended_route": "efficiency_play",
            "manual_review_required": False,
            "commentary": text[:300] if text else "AI недоступен",
        }


def generate_portfolio_commentary(projects: list, stats: dict) -> str:
    """
    Generate a 3-4 sentence executive summary of the entire portfolio.
    Called only when include_ai=True in an export request.
    """
    approved_count  = stats.get("by_status", {}).get("approved", 0)
    pending_count   = stats.get("by_status", {}).get("pending_approval", 0)
    high_risk_count = stats.get("high_risk_count", 0)
    total_npv       = stats.get("total_npv", 0)
    avg_irr         = stats.get("avg_irr", "н/д")
    budget          = stats.get("investment_budget")
    approved_inv    = stats.get("approved_investment", 0)

    project_lines = "\n".join(
        f"  • {p.get('name', '—')} | статус: {p.get('status', '?')} "
        f"| NPV: {(p.get('metrics') or {}).get('npv', 'н/д')} ₽ "
        f"| IRR: {(p.get('metrics') or {}).get('irr', 'н/д')}%"
        for p in projects[:20]
    )

    budget_line = (
        f"Инвестиционный бюджет: {budget:,.0f} ₽, использовано: {approved_inv:,.0f} ₽."
        if budget else "Инвестиционный бюджет не задан."
    )

    prompt = (
        f"Ты — CFO-ассистент. Напиши краткое исполнительное резюме портфеля "
        f"(3-4 предложения) для управленческого отчёта.\n\n"
        f"Итого проектов: {stats.get('total', 0)}, "
        f"одобрено: {approved_count}, на рассмотрении: {pending_count}, "
        f"высокорисковых: {high_risk_count}.\n"
        f"Суммарный NPV: {total_npv:,.0f} ₽, средний IRR: {avg_irr}%.\n"
        f"{budget_line}\n\n"
        f"Проекты:\n{project_lines}\n\n"
        "Сформулируй ключевые выводы и рекомендации для руководства."
    )
    return _chat(prompt, max_tokens=400)


def analyze_project(project: dict, metrics: dict) -> dict:
    """Analyze anomalies and give AI commentary for project detail page."""
    project_type = project.get("project_type", "investment")

    if project_type == "operational":
        fm = project.get("financial_model") or {}
        vs = project.get("value_score_data") or {}
        op_metric = fm.get("op_metrics") or project.get("op_metrics", "—")
        op_baseline = fm.get("op_baseline") or project.get("op_baseline", "—")
        op_target = fm.get("op_target") or project.get("op_target", "—")
        op_economics = fm.get("op_economics") or project.get("op_economics", "—")
        prompt = (
            f"Ты — AI-аналитик инвестиционного процессора. Проанализируй операционный проект.\n\n"
            f"Инициатива: «{project.get('name', '?')}» (статус: {project.get('status', '?')})\n"
            f"Категория: {fm.get('op_category') or project.get('op_category', '—')}\n"
            f"Тип инвестиции: {fm.get('op_investment_type') or project.get('op_investment_type', '—')}\n"
            f"Ключевая метрика: {op_metric}\n"
            f"Baseline: {op_baseline}\n"
            f"Target: {op_target}\n"
            f"Экономика/Payback: {op_economics}\n\n"
            f"Value Score: {vs.get('total', '—')} / 50 (зона: {vs.get('band', '—')})\n"
            f"  - Влияние на EV (×3): {vs.get('ev_impact', '—')}\n"
            f"  - Срочность (×2): {vs.get('urgency', '—')}\n"
            f"  - Прогнозируемость ROI (×1): {vs.get('roi_predictability', '—')}\n"
            f"  - Масштабируемость (×2): {vs.get('scalability', '—')}\n"
            f"  - Unit-экономика (×2): {vs.get('unit_economics', '—')}\n\n"
            "Проанализируй реалистичность метрики и целевых показателей. "
            "Выяви аномалии: слишком амбициозный Target, противоречие между метрикой и экономикой, "
            "несоответствие Value Score и заявленного эффекта.\n\n"
            "Верни строго JSON (только JSON, без Markdown):\n"
            '{"comment": "1-2 предложения общего вывода",'
            '"anomalies": ["аномалия или риск 1", "аномалия 2"],'
            '"comparison": "краткое сравнение с отраслевыми бенчмарками по данной метрике",'
            '"metrics_analysis": {'
            '"metric_name": "название метрики",'
            '"baseline_assessment": "оценка стартовой точки",'
            '"target_feasibility": "реалистичность цели: низкая|средняя|высокая",'
            '"target_feasibility_comment": "почему реалистично или нет",'
            '"recommended_tracking": "как отслеживать: ежемесячно/еженедельно и что именно"'
            "}}"
        )
        text = _strip_fences(_chat(prompt, max_tokens=700))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"comment": text, "anomalies": [], "comparison": "", "metrics_analysis": None}
    else:
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
