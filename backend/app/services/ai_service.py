"""
AI service — wraps OpenAI and Anthropic APIs for project-level features:
  - generate_description: formulate project description from key fields
  - generate_risks: produce risks & assumptions analysis
  - generate_risk_score: AI risk scoring for operational projects
  - analyze_project: detect anomalies, compare with portfolio median

Active provider is controlled via settings_store.get_ai_provider() ('openai' | 'anthropic').
"""

import json
from typing import Optional
from openai import OpenAI

from .. import settings_store


OPENAI_MODEL = "gpt-5.4"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"

SYSTEM_PROMPT = (
    "Ты — AI-ассистент инвестиционного процессора. "
    "Отвечай строго по-русски, лаконично и профессионально. "
    "Используй финансовую терминологию. "
    "Не добавляй вводных фраз вроде «Конечно!» или «С удовольствием помогу»."
)


def _chat_openai(prompt: str, max_tokens: int = 700) -> str:
    key = settings_store.get_openai_key()
    if not key:
        raise ValueError("OpenAI API ключ не настроен. Откройте Настройки и введите ключ.")
    response = OpenAI(api_key=key).chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=max_tokens,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


def _chat_anthropic(prompt: str, max_tokens: int = 700) -> str:
    import anthropic
    key = settings_store.get_anthropic_key()
    if not key:
        raise ValueError("Anthropic API ключ не настроен. Откройте Настройки и введите ключ.")
    message = anthropic.Anthropic(api_key=key).messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _chat_routerai(prompt: str, max_tokens: int = 700) -> str:
    key = settings_store.get_routerai_key()
    if not key:
        raise ValueError("RouterAI API ключ не настроен. Откройте Настройки и введите ключ.")
    model = settings_store.get_routerai_model()
    response = OpenAI(api_key=key, base_url=ROUTERAI_BASE_URL).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


def _chat(prompt: str, max_tokens: int = 700) -> str:
    """Dispatch to active AI provider."""
    provider = settings_store.get_ai_provider()
    if provider == "anthropic":
        return _chat_anthropic(prompt, max_tokens)
    if provider == "routerai":
        return _chat_routerai(prompt, max_tokens)
    return _chat_openai(prompt, max_tokens)


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
    )
    budget_rows = application.get("op_budget_rows", [])
    if budget_rows:
        budget_lines = []
        for row in budget_rows:
            cat = row.get("category") or "—"
            totals = row.get("annual_totals", [])
            totals_str = ", ".join(f"Год {i+1}: {v:,.0f} ₽" for i, v in enumerate(totals))
            budget_lines.append(f"  {cat}: {totals_str}")
        prompt += "Бюджет по статьям:\n" + "\n".join(budget_lines) + "\n\n"
    prompt += (
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


def analyze_fact_vs_plan(
    project_name: str,
    fact_rows: list,
    financial_model: dict,
    metrics: dict,
) -> dict:
    """
    Deep plan vs fact analysis: compares actual results against plan values
    and against the original financial model projections.
    Returns structured JSON with comment, key_deviations, model_comparison,
    npv_irr_risk, recommendations.
    """
    fm = financial_model or {}
    m = metrics or {}

    lines = []
    for e in fact_rows:
        fv = e.get("fact_value")
        pv = e.get("plan_value")
        if fv is None:
            continue
        if pv and pv != 0:
            dev = round((fv - pv) / pv * 100, 1)
            sign = "+" if dev >= 0 else ""
            icon = "✅" if dev >= -5 else ("⚠️" if dev >= -20 else "❌")
            dev_str = f"{sign}{dev}%"
        else:
            dev, sign, icon, dev_str = None, "", "—", "н/д"
        lines.append(
            f"  {icon} {e['metric_name']} {e['year']}/{e['month']:02d}: "
            f"план={pv}, факт={fv}, откл.={dev_str}"
        )

    fact_block = "\n".join(lines) or "Фактических данных не введено."

    inv = fm.get("initialInvestment") or 0
    num_years = fm.get("numYears") or "—"
    rev_model = fm.get("revenueModel") or "—"
    price = fm.get("price") or "—"
    conv = fm.get("conversionRate") or "—"
    churn = fm.get("churnRate") or "—"
    nwc = fm.get("nwc") or "—"

    npv = m.get("npv")
    irr = m.get("irr")
    dpp = m.get("dpp")
    ltv_cac = m.get("ltvCac")

    prompt = (
        f"Ты — AI-финансовый аналитик. Проведи детальный анализ план/факт для инвестиционного проекта.\n\n"
        f"ПРОЕКТ: «{project_name}»\n\n"
        f"═══ ДАННЫЕ ПЛАН / ФАКТ ═══\n{fact_block}\n\n"
        f"═══ ПАРАМЕТРЫ ФИНАНСОВОЙ МОДЕЛИ ═══\n"
        f"  Начальные инвестиции: {inv:,.0f} ₽\n"
        f"  Горизонт: {num_years} лет\n"
        f"  Модель выручки: {rev_model}\n"
        f"  Цена / ARPU: {price} ₽\n"
        f"  Конверсия: {conv}%\n"
        f"  Отток (churn): {churn}% в мес.\n"
        f"  NWC: {nwc} ₽\n\n"
        f"═══ РАСЧЁТНЫЕ ФИНАНСОВЫЕ МЕТРИКИ ═══\n"
        f"  NPV: {f'{npv:,.0f} ₽' if isinstance(npv, (int,float)) else 'н/д'}\n"
        f"  IRR: {f'{irr}%' if irr is not None else 'н/д'}\n"
        f"  DPP: {f'{dpp} лет' if dpp is not None else 'н/д'}\n"
        f"  LTV/CAC: {ltv_cac if ltv_cac is not None else 'н/д'}\n\n"
        "Проведи анализ по четырём направлениям:\n"
        "1. Ключевые отклонения от плана (особенно >±10%) — вероятные причины\n"
        "2. Как факт соотносится с параметрами финансовой модели (конверсия, отток, ARPU)\n"
        "3. Риск недостижения NPV и IRR при текущей динамике\n"
        "4. Конкретные рекомендации по корректирующим действиям\n\n"
        "Верни строго JSON (только JSON, без Markdown-блоков):\n"
        '{"comment": "2-3 предложения — общий вывод по исполнению плана",'
        '"key_deviations": ['
        '{"metric": "название метрики", "deviation_pct": число_или_null, '
        '"assessment": "норма|тревога|критично", "reason": "вероятная причина отклонения"}'
        '],'
        '"model_comparison": "1-2 предложения: как факт соотносится с параметрами модели",'
        '"npv_irr_risk": "низкий|средний|высокий",'
        '"npv_irr_comment": "1 предложение о риске достижения NPV/IRR",'
        '"recommendations": ["действие 1", "действие 2", "действие 3"]}'
    )

    text = _strip_fences(_chat(prompt, max_tokens=1000))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "comment": text[:500] if text else "Ошибка AI",
            "key_deviations": [],
            "model_comparison": "",
            "npv_irr_risk": "н/д",
            "npv_irr_comment": "",
            "recommendations": [],
        }


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


def extract_requested_amount(text: str, budget_summary: str = "") -> str:
    """Extract requested monetary amount from operational request description."""
    budget_section = f"\n\n{budget_summary}" if budget_summary else ""
    prompt = (
        "Из данных операционной заявки определи ИТОГОВУЮ запрашиваемую сумму инвестиций.\n\n"
        "Правила приоритета (строго сверху вниз, остановись на первом совпадении):\n"
        "1. «Общий бюджет» — высший приоритет. Если есть «Общий бюджет: X» — вернуть X.\n"
        "2. «Итого», «Всего», «Суммарно» — вернуть следующее за ними число.\n"
        "3. «Требуемый план ФОТ», «Запрашивается», «Необходимо», «Требуемый бюджет» — вернуть следующее за ними число.\n"
        "4. Если есть «текущий лимит» и «требуемый план» — вернуть ТРЕБУЕМЫЙ ПЛАН, а НЕ дельту/увеличение.\n"
        "5. Если есть структурированный бюджет (раздел ниже) — использовать «ИТОГО за период» или «Среднемесячно».\n"
        "6. Только если ничего выше не найдено — взять единственную или первую сумму.\n"
        "7. Если сумма не определена — вернуть «не указана».\n\n"
        "ВАЖНО: НЕ выбирать первую встреченную сумму — искать САМУЮ ИТОГОВУЮ/АГРЕГИРОВАННУЮ.\n"
        "Если указан диапазон (например 3 360 000–3 600 000 ₽) — вернуть его целиком.\n\n"
        "Верни ТОЛЬКО сумму с валютой и периодом (например: «3 360 000–3 600 000 ₽/год» или «696 047 ₽/мес»).\n"
        "Никакого пояснительного текста — только сумма или «не указана».\n\n"
        f"Текст заявки:\n{text[:2500]}"
        f"{budget_section}"
    )
    return _chat(prompt, max_tokens=80)
