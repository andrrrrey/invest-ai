"""
Excel export service — builds a .xlsx workbook for portfolio management reports.
"""

import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

PURPLE_HEX = "FF5E5CE6"
LIGHT_GRAY_HEX = "FFF2F2F2"
RED_HEX = "FFFFD7D7"
YELLOW_HEX = "FFFFF3CD"
GREEN_HEX = "FFD4EDDA"
WHITE_HEX = "FFFFFFFF"

_THIN = Side(style="thin", color="FFD0D0D0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _header_fill() -> PatternFill:
    return PatternFill("solid", fgColor=PURPLE_HEX)


def _gray_fill() -> PatternFill:
    return PatternFill("solid", fgColor=LIGHT_GRAY_HEX)


def _apply_header(ws, values: list[str], row: int = 1):
    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx, value=val)
        cell.font = Font(bold=True, color=WHITE_HEX)
        cell.fill = _header_fill()
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER


def _auto_width(ws, min_width: int = 10, max_width: int = 40):
    for col in ws.columns:
        max_len = min_width
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, min(len(str(cell.value)), max_width))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = max_len + 2


def _risk_fill(risk_level: str) -> PatternFill | None:
    rl = (risk_level or "").lower()
    if "высок" in rl:
        return PatternFill("solid", fgColor=RED_HEX)
    if "средн" in rl or "умерен" in rl:
        return PatternFill("solid", fgColor=YELLOW_HEX)
    if "низк" in rl:
        return PatternFill("solid", fgColor=GREEN_HEX)
    return None


def _get_risk_level(project: dict) -> str:
    risks = project.get("risks_data") or {}
    ai = risks.get("ai_assessment") or {}
    return ai.get("risk_level") or risks.get("overall_risk") or "—"


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def _sheet_portfolio_summary(wb: Workbook, stats: dict, period_label: str):
    ws = wb.active
    ws.title = "Сводка портфеля"

    # Title row
    ws.merge_cells("A1:B1")
    title_cell = ws["A1"]
    title_cell.value = f"Портфель: {period_label}"
    title_cell.font = Font(bold=True, color=WHITE_HEX, size=13)
    title_cell.fill = _header_fill()
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    by_status = stats.get("by_status", {})
    by_type   = stats.get("by_type", {})

    rows = [
        ("Всего проектов", stats.get("total", 0)),
        ("", ""),
        ("По статусу", ""),
        ("  Черновик",              by_status.get("draft", 0)),
        ("  На рассмотрении",       by_status.get("pending_approval", 0)),
        ("  Одобрено",              by_status.get("approved", 0)),
        ("  Отклонено",             by_status.get("rejected", 0)),
        ("", ""),
        ("По типу", ""),
        ("  Инвестиционные",        by_type.get("investment", 0)),
        ("  Операционные",          by_type.get("operational", 0)),
        ("", ""),
        ("Суммарный NPV (₽)",       stats.get("total_npv", 0)),
        ("Средний IRR (%)",         stats.get("avg_irr", "н/д")),
        ("Высокорисковых проектов", stats.get("high_risk_count", 0)),
        ("", ""),
        ("Инвестиционный бюджет (₽)",   stats.get("investment_budget", "не задан")),
        ("Одобренные инвестиции (₽)",   stats.get("approved_investment", 0)),
        ("Доступно для инвестиций (₽)", stats.get("available_for_investment", "н/д")),
    ]

    for i, (label, value) in enumerate(rows, start=2):
        label_cell = ws.cell(row=i, column=1, value=label)
        value_cell = ws.cell(row=i, column=2, value=value)
        if label and not label.startswith(" ") and label not in ("По статусу", "По типу"):
            label_cell.font = Font(bold=True)
        if label in ("По статусу", "По типу"):
            label_cell.font = Font(bold=True, italic=True)
            label_cell.fill = _gray_fill()
            value_cell.fill = _gray_fill()
        label_cell.border = _BORDER
        value_cell.border = _BORDER
        value_cell.alignment = Alignment(horizontal="right")

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 22


def _sheet_all_projects(wb: Workbook, projects: list[dict]):
    ws = wb.create_sheet("Все проекты")

    headers = [
        "ID", "Название", "Бизнес-юнит", "Тип", "Стадия", "Статус", "Владелец",
        "Дата начала", "NPV (₽)", "IRR (%)", "DPP (лет)", "PI",
        "LTV/CAC", "CAC (₽)", "ARPU (₽)", "Отток (%)", "Gross Margin (%)",
        "Уровень риска", "Маршрут решения",
    ]
    _apply_header(ws, headers)
    ws.freeze_panes = "A2"

    for p in projects:
        m = p.get("metrics") or {}
        risk_level = _get_risk_level(p)
        row = [
            p.get("id"),
            p.get("name"),
            p.get("business_unit"),
            p.get("project_type"),
            p.get("stage"),
            p.get("status"),
            p.get("owner"),
            str(p.get("start_date") or ""),
            m.get("npv"),
            m.get("irr"),
            m.get("dpp"),
            m.get("pi"),
            m.get("ltvCac"),
            m.get("cac"),
            m.get("arpu"),
            m.get("avgChurn"),
            m.get("grossMargin"),
            risk_level,
            p.get("decision_route"),
        ]
        ws.append(row)
        row_idx = ws.max_row
        fill = _risk_fill(risk_level)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = _BORDER
            if fill:
                cell.fill = fill

    _auto_width(ws)


def _sheet_annual_cash_flows(wb: Workbook, projects: list[dict]):
    ws = wb.create_sheet("Денежные потоки")

    year_headers = [f"Год {i}" for i in range(6)]
    top_headers = ["Проект", "Показатель"] + year_headers
    _apply_header(ws, top_headers)
    ws.freeze_panes = "A2"

    metric_keys = [
        ("annualRevenue",       "Выручка (₽)"),
        ("totalCosts",          "Затраты (₽)"),
        ("netCashFlow",         "Чистый ДП (₽)"),
        ("discountedCF",        "Дисконт. ДП (₽)"),
        ("cumulativeDcfSeries", "Накопл. ДДП (₽)"),
    ]

    for p in projects:
        if p.get("project_type") == "operational":
            continue
        m = p.get("metrics") or {}
        name = p.get("name", "—")
        first_row = True
        for key, label in metric_keys:
            series = m.get(key) or []
            # Pad or trim to 6 values (Year 0..5)
            values = list(series[:6]) + [None] * max(0, 6 - len(series))
            row_data = [name if first_row else "", label] + values
            ws.append(row_data)
            row_idx = ws.max_row
            for col_idx in range(1, len(top_headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = _BORDER
                if first_row:
                    cell.fill = _gray_fill()
            first_row = False

    _auto_width(ws)


def _sheet_quarterly_user_metrics(wb: Workbook, projects: list[dict]):
    ws = wb.create_sheet("Квартальные метрики")

    quarter_headers = [f"Y{y+1}Q{q+1}" for y in range(5) for q in range(4)]
    top_headers = ["Проект", "Показатель"] + quarter_headers
    _apply_header(ws, top_headers)
    ws.freeze_panes = "A2"

    for p in projects:
        name = p.get("name", "—")
        m = p.get("metrics") or {}

        if p.get("project_type") == "operational":
            ws.append([name, "Операционный проект — квартальные данные недоступны"])
            ws.cell(ws.max_row, 1).font = Font(italic=True, color="FF888888")
            continue

        paid_users = m.get("paidUsers") or []
        revenue    = m.get("revenue") or []

        def flatten_matrix(matrix):
            result = []
            for year_data in matrix[:5]:
                if isinstance(year_data, list):
                    result.extend(year_data[:4])
                    result.extend([None] * max(0, 4 - len(year_data)))
                else:
                    result.extend([None, None, None, None])
            return result + [None] * max(0, 20 - len(result))

        pu_flat  = flatten_matrix(paid_users)
        rev_flat = flatten_matrix(revenue)

        for label, values in [("Платные пользователи", pu_flat), ("Выручка (₽)", rev_flat)]:
            ws.append([name, label] + values[:20])
            row_idx = ws.max_row
            for col_idx in range(1, len(top_headers) + 1):
                ws.cell(row=row_idx, column=col_idx).border = _BORDER
            name = ""  # only print name once

    _auto_width(ws, max_width=15)


def _sheet_ai_commentary(wb: Workbook, projects: list[dict], ai_commentaries: dict):
    ws = wb.create_sheet("AI-комментарии")
    _apply_header(ws, ["Проект", "AI-комментарий"])
    ws.freeze_panes = "A2"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 80

    for p in projects:
        commentary = ai_commentaries.get(p.get("id"), "—")
        ws.append([p.get("name", "—"), commentary])
        row_idx = ws.max_row
        ws.row_dimensions[row_idx].height = 60
        for col_idx in (1, 2):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = _BORDER


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_excel(
    projects: list[dict],
    stats: dict,
    detail_level: str,
    include_ai: bool,
    ai_commentaries: dict,
    period_label: str,
) -> io.BytesIO:
    """
    Build a .xlsx workbook and return it as a BytesIO stream.

    :param projects:        List of project dicts (id, name, metrics, risks_data, …)
    :param stats:           Portfolio stats dict (same shape as GET /api/v1/stats/)
    :param detail_level:    "summary" or "full"
    :param include_ai:      Whether to add the AI commentary sheet
    :param ai_commentaries: {project_id: commentary_text}
    :param period_label:    Human-readable period string, e.g. "Q1 2026"
    """
    wb = Workbook()

    _sheet_portfolio_summary(wb, stats, period_label)
    _sheet_all_projects(wb, projects)

    if detail_level == "full":
        _sheet_annual_cash_flows(wb, projects)
        _sheet_quarterly_user_metrics(wb, projects)

    if include_ai:
        _sheet_ai_commentary(wb, projects, ai_commentaries)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
