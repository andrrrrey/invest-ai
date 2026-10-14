"""Проект приказа по согласованному инвестиционному проекту / операционной
заявке: выделение (передача) денежных средств на реализацию.

Шаблон временный — по договорённости его заменит шаблон приказа заказчика.
Формат документа и маршрут согласования те же, что у приказа по контракту
(``order_service``).
"""

from __future__ import annotations

import json
from typing import List

from ..models.project import Project
from .order_service import DEFAULT_SIGNER, _d

TRANCHE_COLUMNS = ["№", "Сумма, ₽", "Плановая дата", "Условие / назначение", "Статус"]
_TRANCHE_STATUS = {"requested": "Запрошен", "approved": "Одобрен", "paid": "Выплачен"}


def _money(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _operational_budget(fm: dict) -> float:
    total = 0.0
    for row in fm.get("op_budget_rows") or []:
        for year in row.get("monthlyValues") or []:
            for v in year or []:
                try:
                    total += float(v or 0)
                except (TypeError, ValueError):
                    pass
    return total


def project_facts(project: Project) -> dict:
    fm = project.financial_model or {}
    tranches = sorted(project.tranches or [], key=lambda t: (t.order_index or 0, t.id))
    if tranches:
        amount = sum(float(t.amount or 0) for t in tranches)
    elif (project.project_type or "") == "operational":
        amount = _operational_budget(fm)
    else:
        try:
            amount = abs(float(fm.get("initialInvestment") or 0))
        except (TypeError, ValueError):
            amount = 0.0
    metrics = project.metrics or {}
    return {
        "kind": "операционной заявки" if (project.project_type or "") == "operational" else "инвестиционного проекта",
        "name": project.name or "",
        "business_unit": project.business_unit or "",
        "owner": project.owner or "ответственного",
        "description": project.description or "",
        "amount": amount,
        "start": project.start_date,
        "npv": metrics.get("npv"),
        "irr": metrics.get("irr"),
        "tranches": [
            [str(i), _money(float(t.amount or 0)), _d(t.planned_date), t.description or "—",
             _TRANCHE_STATUS.get(t.status or "", t.status or "—")]
            for i, t in enumerate(tranches, start=1)
        ],
    }


def template_project_order(project: Project) -> dict:
    f = project_facts(project)
    amount = f"{_money(f['amount'])} (сумма прописью) рублей" if f["amount"] else "___ (сумма прописью) рублей"
    schedule = "согласно графику траншей (приложение к настоящему приказу)" if f["tranches"] \
        else "единовременно / по графику, утверждаемому финансовым директором"
    points = [
        f"Утвердить реализацию {f['kind']} «{f['name']}» (далее — Проект)"
        + (f" в подразделении «{f['business_unit']}»" if f["business_unit"] else "") + ".",
        f"Выделить на реализацию Проекта денежные средства в размере {amount} {schedule}.",
        f"Назначить {f['owner']} ответственным за реализацию Проекта и целевое использование выделенных средств.",
        "Финансовому директору обеспечить финансирование Проекта в пределах утверждённой суммы и графика.",
        f"{f['owner']} ежемесячно, до 5-го числа месяца, следующего за отчётным, представлять финансовому "
        "директору отчёт о ходе реализации Проекта и фактическом расходовании средств.",
        "Контроль за исполнением настоящего приказа оставляю за собой.",
    ]
    return {
        "title": f"О выделении денежных средств на реализацию {f['kind']} «{f['name']}»",
        "preamble": (
            f"В целях реализации {f['kind']} «{f['name']}», согласованного в установленном порядке, "
            "и обеспечения контроля за целевым использованием денежных средств,"
        ),
        "points": points,
        "appendix_title": f"График финансирования {f['kind']} «{f['name']}»" if f["tranches"] else "",
        "appendix_columns": TRANCHE_COLUMNS,
        "appendix_rows": f["tranches"],
        "signer_position": DEFAULT_SIGNER[0],
        "signer_name": DEFAULT_SIGNER[1],
        "review_notes": [
            "Шаблон приказа о выделении средств временный — сверьте с шаблоном компании.",
            "Проверьте сумму прописью, источник финансирования и график траншей.",
        ],
    }


def ai_project_order(project: Project) -> dict:
    """Уточнение формулировок шаблона AI-ассистентом (структура и данные — из шаблона)."""
    from . import ai_service

    base = template_project_order(project)
    f = project_facts(project)
    prompt = (
        "Ты — юрист компании. Улучши формулировки проекта приказа о выделении денежных средств "
        "на реализацию проекта. Сохрани фирменный стиль: преамбула заканчивается запятой, пункты без "
        "номеров, последний пункт — «Контроль за исполнением настоящего приказа оставляю за собой.». "
        "Не выдумывай суммы, даты и ФИО — используй только данные ниже; неизвестное оставь «___».\n\n"
        f"— Проект: «{f['name']}» ({f['kind']}), подразделение: {f['business_unit'] or '—'}\n"
        f"— Ответственный: {f['owner']}\n— Сумма: {_money(f['amount']) if f['amount'] else '___'} ₽\n"
        f"— Описание: {f['description'][:1500] or '—'}\n"
        f"— Транши: {len(f['tranches'])}\n\n"
        "Черновик:\n" + json.dumps({k: base[k] for k in ("title", "preamble", "points")}, ensure_ascii=False) + "\n\n"
        'Верни только JSON без Markdown: {"title": "...", "preamble": "...", "points": ["..."], '
        '"review_notes": ["что проверить юристу"]}'
    )
    raw = ai_service._chat(prompt, max_tokens=2000,
                           extra_terms={"project": [f["name"]], "person": [f["owner"]]},
                           action="ai.order", target_type="project", target_id=str(project.id))
    data = json.loads(ai_service._strip_fences(raw))
    points: List[str] = [str(p).strip() for p in data.get("points") or [] if str(p).strip()]
    if not data.get("title") or not points:
        raise ValueError("AI вернул неполный приказ")
    base.update({
        "title": str(data["title"]).strip(),
        "preamble": str(data.get("preamble") or base["preamble"]).strip(),
        "points": points,
        "review_notes": [str(n) for n in data.get("review_notes") or []] + base["review_notes"][:1],
    })
    return base
