"""
PDF export service — renders a management report HTML page to PDF bytes via WeasyPrint.
"""

import io
import html as _htmllib
import re

from weasyprint import HTML


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value, suffix: str = "", decimals: int = 0) -> str:
    if value is None:
        return "н/д"
    try:
        v = float(value)
        return f"{v:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _status_label(status: str) -> str:
    return {
        "draft": "Черновик",
        "pending_approval": "На рассмотрении",
        "approved": "Одобрено",
        "rejected": "Отклонено",
    }.get(status or "", status or "—")


def _type_label(ptype: str) -> str:
    return {
        "investment": "Инвестиционный",
        "operational": "Операционный",
        "smart_contract": "Смарт-контракт",
    }.get(ptype or "", ptype or "—")


def _route_label(route: str) -> str:
    return {
        "fast_track": "FAST TRACK",
        "efficiency_play": "EFFICIENCY PLAY",
        "backlog_stop": "BACKLOG / STOP",
        "manual_review": "Ручная проверка",
    }.get(route or "", route or "—")


def _route_meta(route: str) -> tuple[str, str]:
    """(threshold label, route wording) for the Decision Routing section."""
    return {
        "fast_track": ("Fast Track (40–50/50)", "Высокий потенциал создания ценности; "
                       "автоматическое утверждение на Discovery/Pilot, ресурсы из резерва."),
        "efficiency_play": ("Efficiency Play (25–39/50)", "Умеренный потенциал; "
                            "запуск с контролем эффективности и stage-gates."),
        "backlog_stop": ("Backlog / Stop (0–24/50)", "Низкий потенциал; "
                         "отправляется в бэклог или останавливается."),
        "manual_review": ("Manual Review", "Требуется ручная экспертная оценка."),
    }.get(route or "", ("—", "—"))


def _esc(value) -> str:
    """Escape a plain value for HTML output."""
    if value is None:
        return "—"
    return _htmllib.escape(str(value))


_HTML_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]*>")


def _html_or_text(value) -> str:
    """
    op_* thesis-like fields may already contain HTML from the rich editor.
    If the value looks like HTML, pass it through; otherwise escape and
    convert newlines to <br>.
    """
    if value is None or value == "":
        return "—"
    s = str(value)
    if _HTML_TAG_RE.search(s):
        return s
    return _htmllib.escape(s).replace("\n", "<br>")


def _risk_color(risk_level: str) -> str:
    rl = (risk_level or "").lower()
    if "высок" in rl:
        return "#dc3545"
    if "средн" in rl or "умерен" in rl:
        return "#ffc107"
    if "низк" in rl:
        return "#28a745"
    return "#6c757d"


def _get_risk_level(project: dict) -> str:
    risks = project.get("risks_data") or {}
    ai = risks.get("ai_assessment") or {}
    return ai.get("risk_level") or risks.get("overall_risk") or "—"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

@page {
    margin: 15mm 15mm 20mm 15mm;
    @bottom-center {
        content: "Страница " counter(page) " из " counter(pages);
        font-size: 9pt;
        color: #888;
    }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Plus Jakarta Sans', Arial, sans-serif; font-size: 10pt; color: #1C1C1E; line-height: 1.5; }

.page-break { page-break-before: always; }

/* Cover */
.cover { padding: 40mm 20mm; text-align: center; }
.cover-title { font-size: 28pt; font-weight: 700; color: #5E5CE6; margin-bottom: 10px; }
.cover-subtitle { font-size: 14pt; color: #555; margin-bottom: 30px; }
.cover-meta { font-size: 10pt; color: #888; }
.cover-kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 40px; }
.cover-kpi-card { background: #F8F7F3; border-radius: 12px; padding: 16px; text-align: center; }
.cover-kpi-value { font-size: 18pt; font-weight: 700; color: #5E5CE6; }
.cover-kpi-label { font-size: 9pt; color: #888; margin-top: 4px; }

/* Sections */
.section { margin-bottom: 24px; }
.section-title { font-size: 14pt; font-weight: 700; color: #5E5CE6; margin-bottom: 12px;
                 border-bottom: 2px solid #5E5CE6; padding-bottom: 4px; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 9pt; }
th { background: #5E5CE6; color: white; padding: 7px 8px; text-align: left; font-weight: 600; }
td { padding: 6px 8px; border-bottom: 1px solid #E0E0E0; vertical-align: top; }
tr:nth-child(even) td { background: #F8F7F3; }
.num { text-align: right; }

/* Risk badge */
.risk-badge { display: inline-block; padding: 2px 8px; border-radius: 20px; color: white;
              font-size: 8pt; font-weight: 600; }

/* Project card (full detail) */
.project-card { border: 1px solid #E0E0E0; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.project-card-title { font-size: 12pt; font-weight: 700; margin-bottom: 8px; }
.project-meta { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; margin-bottom: 12px; font-size: 9pt; color: #555; }
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.metric-box { background: #F8F7F3; border-radius: 6px; padding: 8px; text-align: center; }
.metric-value { font-size: 11pt; font-weight: 700; color: #5E5CE6; }
.metric-label { font-size: 8pt; color: #888; margin-top: 2px; }
.risks-list { font-size: 9pt; }
.risks-list li { margin-bottom: 4px; }
.ai-block { background: #F0F0FF; border-left: 3px solid #5E5CE6; padding: 10px 12px;
            border-radius: 0 6px 6px 0; margin-top: 12px; font-size: 9pt; font-style: italic; }

/* Detailed per-project report */
.project-report + .project-report { page-break-before: always; }
.report-doc-title { font-size: 18pt; font-weight: 700; color: #1C1C1E; margin-bottom: 4px; }
.report-doc-sub { font-size: 10pt; color: #777; margin-bottom: 16px; }
.summary-box { background: #E2F3E7; border-radius: 8px; padding: 12px 14px; margin-bottom: 18px; }
.summary-box .summary-head { font-weight: 700; color: #1F4D78; margin-bottom: 4px; }
.summary-box .summary-body { font-size: 9.5pt; color: #1C1C1E; }
.sub-title { font-size: 11pt; font-weight: 700; color: #1C1C1E; margin: 16px 0 8px; }
.kv-table td { vertical-align: top; }
.kv-table td.kv-key { width: 34%; font-weight: 600; background: #F8F7F3; }
.section-banner { background: #5E5CE6; color: white; font-weight: 700; padding: 7px 10px;
                  border-radius: 6px; font-size: 10pt; margin: 18px 0 10px; }
.prose { font-size: 9.5pt; line-height: 1.55; }
.prose ul { margin: 6px 0 6px 18px; }
.level-badge { display: inline-block; padding: 1px 8px; border-radius: 20px; color: white;
               font-size: 8pt; font-weight: 600; }
"""


# ---------------------------------------------------------------------------
# Detailed per-project report renderers (matching svodnyy_otchet example)
# ---------------------------------------------------------------------------

def _kv_table(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td class='kv-key'>{k}</td><td>{v}</td></tr>" for k, v in rows
    )
    return f"<table class='kv-table'><tbody>{body}</tbody></table>"


def _score_level(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v <= 2:
        return "Незначительный"
    if v <= 3:
        return "Средний"
    return "Высокий"


def _op_budget_total(fm: dict) -> float:
    total = 0.0
    for row in (fm.get("op_budget_rows") or []):
        for v in (row.get("annual_totals") or []):
            try:
                total += float(v or 0)
            except (TypeError, ValueError):
                pass
    return total


def _value_drivers_text(fm: dict) -> str:
    drivers = fm.get("op_value_drivers") or []
    other = fm.get("op_value_drivers_other") or ""
    out = [other if d == "__other__" else d for d in drivers]
    return "; ".join(str(d) for d in out if d) or "—"


def _render_operational_detail(p: dict, ai_comment: str | None) -> str:
    fm = p.get("financial_model") or {}
    vs = p.get("value_score_data") or {}
    risks = p.get("risks_data") or {}
    route = p.get("decision_route")
    threshold, route_wording = _route_meta(route)

    budget_total = _op_budget_total(fm)
    budget_str = _fmt(budget_total, " ₽") if budget_total else (_html_or_text(fm.get("op_requested_resource")))
    overall_risk = risks.get("overall_risk") or _get_risk_level(p)

    # Короткий итог
    summary = (
        f"Value Score: {vs.get('total', '—')}/50. "
        f"Рекомендованный маршрут: {_route_label(route)}. "
        f"Risk Score: {overall_risk}. {route_wording}"
    )

    # Ключевые факты
    resource_str = _html_or_text(fm.get("op_requested_resource"))
    key_facts_rows = [("Запрашиваемый бюджет", budget_str)]
    # When no numeric budget is set, budget_str already falls back to the
    # requested-resource text — avoid showing the same value twice.
    if resource_str != budget_str:
        key_facts_rows.append(("Запрашиваемый ресурс", resource_str))
    key_facts_rows += [
        ("Ключевая метрика", _esc(fm.get("op_metrics"))),
        ("Результат маршрутизации", _route_label(route)),
    ]
    key_facts = _kv_table(key_facts_rows)

    # 1. Паспорт проекта
    mvz = " / ".join(
        str(fm.get(k)) for k in ("op_mvz_main", "op_mvz_sub1", "op_mvz_sub2") if fm.get(k)
    ) or "—"
    passport = _kv_table([
        ("Запрашиваемый ресурс", _html_or_text(fm.get("op_requested_resource"))),
        ("Тип инвестиции", _esc(fm.get("op_investment_type"))),
        ("Категория", _esc(fm.get("op_category"))),
        ("МВЗ", _esc(mvz)),
        ("Бизнес-юнит", _esc(p.get("business_unit"))),
        ("Владелец", _esc(p.get("owner"))),
        ("Ключевая метрика", _esc(fm.get("op_metrics"))),
        ("Value Drivers", _esc(_value_drivers_text(fm))),
    ])

    # 5. Оценка по критериям (Value Score)
    vs_rows = [
        ("Влияние на EV / стоимость бизнеса", 3, vs.get("ev_impact")),
        ("Срочность / Opportunity Cost", 2, vs.get("urgency")),
        ("Прогнозируемость ROI", 1, vs.get("roi_predictability")),
        ("Масштабируемость / x10 Rule", 2, vs.get("scalability")),
        ("Влияние на unit-экономику", 2, vs.get("unit_economics")),
    ]
    vs_body = ""
    for label, weight, score in vs_rows:
        try:
            contrib = f"{int(weight) * int(score)}"
        except (TypeError, ValueError):
            contrib = "—"
        vs_body += (
            f"<tr><td>{label}</td><td class='num'>×{weight}</td>"
            f"<td class='num'>{_esc(score)}</td><td class='num'>{contrib}</td></tr>"
        )
    vs_table = (
        "<table><thead><tr><th>Критерий</th><th class='num'>Вес</th>"
        "<th class='num'>Оценка</th><th class='num'>Вклад</th></tr></thead>"
        f"<tbody>{vs_body}</tbody></table>"
        f"<p class='prose' style='margin-top:6px'><b>Итог Value Score: {vs.get('total', '—')} / 50</b>"
        f"{' (зона: ' + _esc(vs.get('band')) + ')' if vs.get('band') else ''}.</p>"
    )

    # 6. AI Risk Score
    rscores = risks.get("risk_scores") or {}
    risk_rows = [
        ("Риск исполнения", rscores.get("execution_risk")),
        ("Рыночный риск", rscores.get("market_risk")),
        ("Финансовый риск", rscores.get("financial_risk")),
        ("Стратегический риск", rscores.get("strategic_risk")),
    ]
    risk_body = "".join(
        f"<tr><td>{label}</td><td class='num'>{_esc(val)}</td><td>{_score_level(val)}</td></tr>"
        for label, val in risk_rows
    )
    risk_table = (
        f"<p class='prose'><b>Общий уровень риска:</b> {_esc(overall_risk)}.</p>"
        "<table><thead><tr><th>Категория риска</th><th class='num'>Оценка</th>"
        "<th>Уровень</th></tr></thead>"
        f"<tbody>{risk_body}</tbody></table>"
    )
    risk_table += _bullet_block("Причины риск-оценки", risks.get("risk_reasons"))
    risk_table += _bullet_block("Рекомендованные контроли", risks.get("controls"))
    risk_table += _bullet_block("Рекомендации по Stage-Gates", risks.get("stage_gate_recommendations"))

    # 7. Decision Routing
    routing = _kv_table([
        ("Рекомендованный маршрут", _route_label(route)),
        ("Value Score", f"{vs.get('total', '—')} / 50"),
        ("Порог маршрута", threshold),
        ("Формулировка маршрута", route_wording),
        ("Risk Score", _esc(overall_risk)),
    ])

    # 8. Заключение
    conclusion = _html_or_text(risks.get("commentary") or ai_comment or "")

    return f"""
<div class="project-report">
  <div class="report-doc-title">{_esc(p.get("name"))}</div>
  <div class="report-doc-sub">Сводный отчёт по проекту · Операционная заявка · {_status_label(p.get("status"))}</div>

  <div class="summary-box">
    <div class="summary-head">Короткий итог по результатам Decision Routing</div>
    <div class="summary-body">{_esc(summary)}</div>
  </div>

  <div class="sub-title">Ключевые факты</div>
  {key_facts}

  <div class="section-banner">1. Паспорт проекта</div>
  {passport}

  <div class="section-banner">2. Инвестиционный тезис</div>
  <div class="prose">{_html_or_text(fm.get("op_investment_thesis"))}</div>

  <div class="section-banner">3. Метрика, базовое и целевое значение</div>
  {_kv_table([
      ("Ключевая метрика", _esc(fm.get("op_metrics"))),
      ("Базовое значение", _html_or_text(fm.get("op_baseline"))),
      ("Целевое значение", _html_or_text(fm.get("op_target"))),
  ])}

  <div class="section-banner">4. Экономика и контроль</div>
  {_kv_table([
      ("Экономика / Payback", _html_or_text(fm.get("op_economics"))),
      ("Stop-loss критерии", _html_or_text(fm.get("op_stop_loss"))),
      ("Stage-gates", _html_or_text(fm.get("op_stage_gates"))),
  ])}

  <div class="section-banner">5. Оценка по критериям (Value Score)</div>
  {vs_table}

  <div class="section-banner">6. AI Risk Score</div>
  {risk_table}

  <div class="section-banner">7. Решение / Decision Routing</div>
  {routing}

  <div class="section-banner">8. Заключение</div>
  <div class="prose">{conclusion}</div>
</div>
"""


def _bullet_block(title: str, items) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{_html_or_text(it)}</li>" for it in items)
    return f"<div class='sub-title'>{title}</div><ul class='prose'>{lis}</ul>"


def _render_investment_detail(p: dict, ai_comment: str | None) -> str:
    m = p.get("metrics") or {}
    risks_data = p.get("risks_data") or {}
    risks_list = risks_data.get("risks") or []
    risk_level = _get_risk_level(p)
    color = _risk_color(risk_level)

    passport = _kv_table([
        ("Статус", _status_label(p.get("status"))),
        ("Бизнес-юнит", _esc(p.get("business_unit"))),
        ("Владелец", _esc(p.get("owner"))),
        ("Стадия", _esc(p.get("stage"))),
        ("Платформа", _esc(p.get("platform"))),
        ("Дата начала", _esc(p.get("start_date"))),
        ("Уровень риска", f"<span class='level-badge' style='background:{color}'>{_esc(risk_level)}</span>"),
    ])

    metrics_html = ""
    for value, label in [
        (_fmt(m.get("npv"), " ₽"), "NPV"),
        (_fmt(m.get("irr"), "%", 2), "IRR"),
        (_fmt(m.get("dpp"), " лет", 1), "DPP"),
        (_fmt(m.get("pi"), "", 2), "PI"),
        (_fmt(m.get("ltvCac"), "", 2), "LTV/CAC"),
        (_fmt(m.get("cac"), " ₽"), "CAC"),
        (_fmt(m.get("arpa"), " ₽"), "ARPA"),
        (_fmt(m.get("grossMargin"), "%", 1), "Gross Margin"),
    ]:
        metrics_html += (
            f"<div class='metric-box'><div class='metric-value'>{value}</div>"
            f"<div class='metric-label'>{label}</div></div>"
        )

    # Cash flow table (Year 0..5)
    cf_keys = [
        ("annualRevenue", "Выручка (₽)"),
        ("totalCosts", "Затраты (₽)"),
        ("netCashFlow", "Чистый ДП (₽)"),
        ("discountedCF", "Дисконт. ДП (₽)"),
        ("cumulativeDcfSeries", "Накопл. ДДП (₽)"),
    ]
    cf_has = any(m.get(k) for k, _ in cf_keys)
    cf_table = ""
    if cf_has:
        head = "".join(f"<th class='num'>Год {i}</th>" for i in range(6))
        body = ""
        for key, label in cf_keys:
            series = (m.get(key) or [])[:6]
            cells = "".join(f"<td class='num'>{_fmt(v)}</td>" for v in series)
            cells += "".join("<td class='num'>—</td>" for _ in range(6 - len(series)))
            body += f"<tr><td>{label}</td>{cells}</tr>"
        cf_table = (
            "<div class='section-banner'>Денежные потоки</div>"
            f"<table><thead><tr><th>Показатель</th>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    risks_items = "".join(f"<li>{_html_or_text(r)}</li>" for r in risks_list) if risks_list else "<li>—</li>"
    ai_block = f'<div class="ai-block">{_html_or_text(ai_comment)}</div>' if ai_comment else ""

    return f"""
<div class="project-report">
  <div class="report-doc-title">{_esc(p.get("name"))}</div>
  <div class="report-doc-sub">Подробный отчёт по проекту · Инвестиционный проект</div>

  <div class="section-banner">1. Паспорт проекта</div>
  {passport}
  {('<div class="prose" style="margin-top:8px">' + _html_or_text(p.get("description")) + '</div>') if p.get("description") else ''}

  <div class="section-banner">2. Финансовые показатели</div>
  <div class="metrics-grid">{metrics_html}</div>

  {cf_table}

  <div class="section-banner">3. Риски</div>
  <ul class="risks-list">{risks_items}</ul>
  {('<div class="section-banner">4. AI-комментарий</div>' + ai_block) if ai_block else ''}
</div>
"""


def _render_smart_contract_detail(p: dict) -> str:
    sc = p.get("smart_contract_data") or {}
    is_leadership = sc.get("scType") == "leadership"
    sc_type_label = "Лидерский контракт" if is_leadership else "Смарт-контракт (coins)"
    contract_type_label = {"single": "Единый (один этап)", "phased": "Поэтапный"}.get(
        sc.get("contractType") or "", sc.get("contractType") or "—"
    )

    passport = _kv_table([
        ("Тип контракта", sc_type_label),
        ("Структура", contract_type_label),
        ("Куратор", _esc(sc.get("curator"))),
        ("Набор команды после согласования", "Да" if sc.get("needsRecruitment") else "Нет"),
        ("Курс NAV", _esc(sc.get("navRate"))),
        ("Итого вознаграждение", _fmt(sc.get("totalRewardRub"), " ₽")),
        ("Итого coins", _fmt(sc.get("totalCoins"), "", 2) if sc.get("totalCoins") is not None else "—"),
    ])

    # Milestones
    milestones = sc.get("milestones") or []
    ms_table = ""
    if milestones:
        body = ""
        for ms in milestones:
            body += (
                f"<tr><td>{_esc(ms.get('title'))}</td>"
                f"<td>{_esc(ms.get('targetDate'))}</td>"
                f"<td class='num'>{_fmt(ms.get('rewardRub'), ' ₽')}</td>"
                f"<td class='num'>{_fmt(ms.get('coins'), '', 2) if ms.get('coins') is not None else '—'}</td></tr>"
            )
        ms_table = (
            "<div class='section-banner'>Milestones</div>"
            "<table><thead><tr><th>Этап</th><th>Дедлайн</th>"
            "<th class='num'>Вознаграждение</th><th class='num'>Coins</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    # Team
    team = sc.get("team") or []
    team_table = ""
    if team:
        body = "".join(
            f"<tr><td>{_esc(t.get('name'))}</td><td>{_esc(t.get('role'))}</td>"
            f"<td class='num'>{_fmt(t.get('coins'), '', 2) if t.get('coins') is not None else '—'}</td></tr>"
            for t in team
        )
        team_table = (
            "<div class='section-banner'>Команда / Coins</div>"
            "<table><thead><tr><th>Участник</th><th>Роль</th>"
            "<th class='num'>Coins</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    # Leadership totals
    lt = sc.get("leadershipTotals") or {}
    lt_table = ""
    if is_leadership and lt:
        lt_table = (
            "<div class='section-banner'>Итоги по лидерскому контракту</div>"
            + _kv_table([
                ("Фикс. оклад / мес.", _fmt(sc.get("fixedSalaryMonthly"), " ₽")),
                ("Итого оклад", _fmt(lt.get("totalSalary"), " ₽")),
                ("Итого премии", _fmt(lt.get("totalBonus"), " ₽")),
                ("Переменная часть (цель)", _fmt(lt.get("variableTotal"), " ₽")),
                ("Grand total", _fmt(lt.get("grand"), " ₽")),
                ("Месяцев", _esc(lt.get("numMonths"))),
                ("Средн. в месяц", _fmt(lt.get("avgMonthly"), " ₽")),
            ])
        )

    return f"""
<div class="project-report">
  <div class="report-doc-title">{_esc(sc.get("name") or p.get("name"))}</div>
  <div class="report-doc-sub">Подробный отчёт по смарт-контракту · {_status_label(p.get("status"))}</div>

  <div class="section-banner">1. Паспорт контракта</div>
  {passport}

  <div class="section-banner">2. Краткое описание</div>
  <div class="prose">{_html_or_text(sc.get("shortDescription"))}</div>

  <div class="section-banner">3. Бизнес-эффект</div>
  <div class="prose">{_html_or_text(sc.get("businessEffect"))}</div>

  {ms_table}
  {lt_table}
  {team_table}
</div>
"""


def _detailed_projects_section(projects: list[dict], ai_commentaries: dict) -> str:
    parts = []
    for p in projects:
        ptype = p.get("project_type")
        ai_comment = ai_commentaries.get(p.get("id"))
        if ptype == "smart_contract":
            parts.append(_render_smart_contract_detail(p))
        elif ptype == "operational":
            parts.append(_render_operational_detail(p, ai_comment))
        else:
            parts.append(_render_investment_detail(p, ai_comment))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_pdf(
    projects: list[dict],
    stats: dict,
    detail_level: str,
    include_ai: bool,
    portfolio_commentary: str,
    ai_commentaries: dict,
    period_label: str,
    generated_by: str,
) -> io.BytesIO:
    """
    Build a detailed per-project PDF report and return it as a BytesIO stream.

    The report always starts directly with the per-project «Сводный отчёт по проекту»
    (no portfolio cover / KPI summary).

    :param projects:             List of project dicts
    :param stats:                Portfolio stats dict (unused; kept for call-site compat)
    :param detail_level:         Kept for compatibility — report is always detailed
    :param include_ai:           Whether AI commentary is included
    :param portfolio_commentary: Unused; kept for call-site compatibility
    :param ai_commentaries:      {project_id: commentary_text}
    :param period_label:         Unused; kept for call-site compatibility
    :param generated_by:         Current user's display name
    """
    parts = [
        f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>",
        _detailed_projects_section(projects, ai_commentaries if include_ai else {}),
        "</body></html>",
    ]
    html_str = "".join(parts)

    pdf_bytes = HTML(string=html_str).write_pdf()
    return io.BytesIO(pdf_bytes)
