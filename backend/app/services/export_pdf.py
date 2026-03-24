"""
PDF export service — renders a management report HTML page to PDF bytes via WeasyPrint.
"""

import io
from datetime import datetime

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
    return {"investment": "Инвестиционный", "operational": "Операционный"}.get(ptype or "", ptype or "—")


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
"""


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _cover_page(stats: dict, period_label: str, generated_by: str) -> str:
    total     = stats.get("total", 0)
    total_npv = _fmt(stats.get("total_npv"), " ₽")
    avg_irr   = _fmt(stats.get("avg_irr"), "%", 2)
    budget    = _fmt(stats.get("investment_budget"), " ₽") if stats.get("investment_budget") else "не задан"
    now       = datetime.now().strftime("%d.%m.%Y %H:%M")

    return f"""
<div class="cover">
  <div class="cover-title">Управленческий отчёт</div>
  <div class="cover-subtitle">Инвестиционный портфель &mdash; {period_label}</div>
  <div class="cover-meta">Сформировал: {generated_by} &nbsp;|&nbsp; {now}</div>
  <div class="cover-kpi-grid">
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{total}</div>
      <div class="cover-kpi-label">Всего проектов</div>
    </div>
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{total_npv}</div>
      <div class="cover-kpi-label">Суммарный NPV</div>
    </div>
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{avg_irr}</div>
      <div class="cover-kpi-label">Средний IRR</div>
    </div>
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{stats.get("by_status", {}).get("approved", 0)}</div>
      <div class="cover-kpi-label">Одобрено</div>
    </div>
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{stats.get("high_risk_count", 0)}</div>
      <div class="cover-kpi-label">Высокорисковых</div>
    </div>
    <div class="cover-kpi-card">
      <div class="cover-kpi-value">{budget}</div>
      <div class="cover-kpi-label">Инвест. бюджет</div>
    </div>
  </div>
</div>
"""


def _portfolio_kpi_section(stats: dict) -> str:
    by_status = stats.get("by_status", {})
    by_type   = stats.get("by_type", {})
    avail     = stats.get("available_for_investment")
    rows = [
        ("Всего проектов",              stats.get("total", 0)),
        ("&nbsp;&nbsp;Черновик",               by_status.get("draft", 0)),
        ("&nbsp;&nbsp;На рассмотрении",        by_status.get("pending_approval", 0)),
        ("&nbsp;&nbsp;Одобрено",               by_status.get("approved", 0)),
        ("&nbsp;&nbsp;Отклонено",              by_status.get("rejected", 0)),
        ("Инвестиционные / Операционные",
            f"{by_type.get('investment', 0)} / {by_type.get('operational', 0)}"),
        ("Суммарный NPV",               _fmt(stats.get("total_npv"), " ₽")),
        ("Средний IRR",                 _fmt(stats.get("avg_irr"), "%", 2)),
        ("Высокорисковых проектов",     stats.get("high_risk_count", 0)),
        ("Инвестиционный бюджет",       _fmt(stats.get("investment_budget"), " ₽") if stats.get("investment_budget") else "не задан"),
        ("Одобренные инвестиции",       _fmt(stats.get("approved_investment"), " ₽")),
        ("Доступно для инвестиций",     _fmt(avail, " ₽") if avail is not None else "н/д"),
    ]
    rows_html = "".join(
        f"<tr><td>{label}</td><td class='num'>{value}</td></tr>" for label, value in rows
    )
    return f"""
<div class="section page-break">
  <div class="section-title">1. KPI портфеля</div>
  <table>
    <thead><tr><th>Показатель</th><th style="text-align:right">Значение</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""


def _top_projects_table(projects: list[dict]) -> str:
    # Sort by NPV desc, take top 10
    def npv_val(p):
        try:
            return float((p.get("metrics") or {}).get("npv") or 0)
        except (TypeError, ValueError):
            return 0.0

    top = sorted(
        [p for p in projects if p.get("project_type") == "investment"],
        key=npv_val, reverse=True
    )[:10]

    rows_html = ""
    for p in top:
        m = p.get("metrics") or {}
        risk_level = _get_risk_level(p)
        color = _risk_color(risk_level)
        rows_html += (
            f"<tr>"
            f"<td>{p.get('name', '—')}</td>"
            f"<td>{_status_label(p.get('status'))}</td>"
            f"<td>{_type_label(p.get('project_type'))}</td>"
            f"<td class='num'>{_fmt(m.get('npv'), ' ₽')}</td>"
            f"<td class='num'>{_fmt(m.get('irr'), '%', 2)}</td>"
            f"<td class='num'>{_fmt(m.get('dpp'), ' лет', 1)}</td>"
            f"<td><span class='risk-badge' style='background:{color}'>{risk_level}</span></td>"
            f"</tr>"
        )

    if not rows_html:
        rows_html = "<tr><td colspan='7'>Инвестиционные проекты отсутствуют</td></tr>"

    return f"""
<div class="section">
  <div class="section-title">2. Топ проекты по NPV</div>
  <table>
    <thead>
      <tr>
        <th>Название</th><th>Статус</th><th>Тип</th>
        <th style="text-align:right">NPV</th><th style="text-align:right">IRR</th>
        <th style="text-align:right">DPP</th><th>Риск</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""


def _risk_breakdown_section(projects: list[dict]) -> str:
    counts: dict[str, int] = {}
    for p in projects:
        rl = _get_risk_level(p)
        counts[rl] = counts.get(rl, 0) + 1

    rows_html = ""
    for rl, cnt in sorted(counts.items()):
        color = _risk_color(rl)
        rows_html += (
            f"<tr><td><span class='risk-badge' style='background:{color}'>{rl}</span></td>"
            f"<td class='num'>{cnt}</td></tr>"
        )
    if not rows_html:
        rows_html = "<tr><td colspan='2'>Нет данных</td></tr>"

    return f"""
<div class="section">
  <div class="section-title">3. Распределение по риску</div>
  <table>
    <thead><tr><th>Уровень риска</th><th style="text-align:right">Кол-во</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""


def _ai_portfolio_section(commentary: str) -> str:
    return f"""
<div class="section">
  <div class="section-title">4. AI-резюме портфеля</div>
  <div class="ai-block">{commentary}</div>
</div>
"""


def _project_detail_card(project: dict, ai_commentary: str | None, section_offset: int) -> str:
    p = project
    m = p.get("metrics") or {}
    risks_data = p.get("risks_data") or {}
    risks_list = risks_data.get("risks") or []
    risk_level = _get_risk_level(p)
    color = _risk_color(risk_level)

    metrics_html = ""
    for value, label in [
        (_fmt(m.get("npv"), " ₽"), "NPV"),
        (_fmt(m.get("irr"), "%", 2), "IRR"),
        (_fmt(m.get("dpp"), " лет", 1), "DPP"),
        (_fmt(m.get("pi"), "", 2), "PI"),
        (_fmt(m.get("ltvCac"), "", 2), "LTV/CAC"),
        (_fmt(m.get("cac"), " ₽"), "CAC"),
        (_fmt(m.get("arpu"), " ₽"), "ARPU"),
        (_fmt(m.get("grossMargin"), "%", 1), "Gross Margin"),
    ]:
        metrics_html += f"""
        <div class="metric-box">
          <div class="metric-value">{value}</div>
          <div class="metric-label">{label}</div>
        </div>"""

    risks_items = "".join(f"<li>{r}</li>" for r in risks_list) if risks_list else "<li>—</li>"

    ai_block = ""
    if ai_commentary:
        ai_block = f'<div class="ai-block">{ai_commentary}</div>'

    return f"""
<div class="project-card">
  <div class="project-card-title">
    {p.get("name", "—")}
    <span class="risk-badge" style="background:{color}; margin-left:8px">{risk_level}</span>
  </div>
  <div class="project-meta">
    <span><b>Статус:</b> {_status_label(p.get("status"))}</span>
    <span><b>Тип:</b> {_type_label(p.get("project_type"))}</span>
    <span><b>Бизнес-юнит:</b> {p.get("business_unit") or "—"}</span>
    <span><b>Владелец:</b> {p.get("owner") or "—"}</span>
    <span><b>Стадия:</b> {p.get("stage") or "—"}</span>
    <span><b>Дата начала:</b> {str(p.get("start_date") or "—")}</span>
  </div>
  <div class="metrics-grid">{metrics_html}</div>
  <div><b>Риски:</b></div>
  <ul class="risks-list">{risks_items}</ul>
  {ai_block}
</div>
"""


def _full_detail_section(projects: list[dict], ai_commentaries: dict, section_num: int) -> str:
    cards = "".join(
        _project_detail_card(p, ai_commentaries.get(p.get("id")), i)
        for i, p in enumerate(projects)
    )
    return f"""
<div class="section page-break">
  <div class="section-title">{section_num}. Детализация проектов</div>
  {cards}
</div>
"""


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
    Build a PDF management report and return it as a BytesIO stream.

    :param projects:             List of project dicts
    :param stats:                Portfolio stats dict
    :param detail_level:         "summary" or "full"
    :param include_ai:           Whether AI sections are included
    :param portfolio_commentary: Plain-text AI summary (empty string if not requested)
    :param ai_commentaries:      {project_id: commentary_text}
    :param period_label:         Human-readable period, e.g. "Q1 2026"
    :param generated_by:         Current user's display name
    """
    parts = [
        f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>",
        _cover_page(stats, period_label, generated_by),
        _portfolio_kpi_section(stats),
        _top_projects_table(projects),
        _risk_breakdown_section(projects),
    ]

    section_num = 4
    if include_ai and portfolio_commentary:
        parts.append(_ai_portfolio_section(portfolio_commentary))
        section_num = 5

    if detail_level == "full":
        parts.append(_full_detail_section(projects, ai_commentaries if include_ai else {}, section_num))

    parts.append("</body></html>")
    html_str = "".join(parts)

    pdf_bytes = HTML(string=html_str).write_pdf()
    return io.BytesIO(pdf_bytes)
