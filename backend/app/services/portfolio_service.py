"""
Агрегация показателей портфеля.

Вынесено из ``api/v1/stats.py`` в переиспользуемый сервис, чтобы одну и ту же
логику могли использовать и REST-эндпоинт, и MCP-инструменты Hermes без
дублирования запросов и правил ролевой видимости.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.tranche import Tranche
from .. import settings_store

_ROUTERAI_LABELS = {
    "anthropic/claude-opus-4.8": "Claude Opus 4.8",
    "anthropic/claude-sonnet-4.6": "Claude Sonnet 4.6",
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
}


def ai_model_label() -> str:
    provider = settings_store.get_ai_provider()
    if provider == "anthropic":
        return "Claude Sonnet 4.6"
    if provider == "routerai":
        model = settings_store.get_routerai_model()
        return _ROUTERAI_LABELS.get(model, model)
    return "GPT-5.4"


def compute_stats(
    db: Session,
    project_type: Optional[str] = None,
    user=None,
) -> dict:
    """Собрать агрегированные показатели портфеля.

    Ролевая видимость: заявитель (``owner``) видит только свои проекты; прочие
    роли и служебный аккаунт (``user is None``) — все. Поведение идентично
    прежнему эндпоинту ``GET /api/v1/stats/``.
    """
    q = db.query(Project)
    if user is not None and getattr(user, "role", None) == "owner":
        q = q.filter(Project.user_id == user.id)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    projects = q.all()

    by_status = {"draft": 0, "pending_approval": 0, "approved": 0, "rejected": 0}
    by_type = {"investment": 0, "operational": 0}
    total_npv = 0.0
    irr_values = []
    high_risk_count = 0

    sc_reward_rub = 0.0
    sc_reward_coins = 0.0
    nav_rate = settings_store.get_nav_rate()

    for p in projects:
        if (p.project_type or "") == "smart_contract":
            scd = p.smart_contract_data or {}
            milestones = scd.get("milestones") or []
            if (scd.get("scType") or "smart") == "leadership":
                lt = scd.get("leadershipTotals") or {}
                grand = lt.get("grand")
                if grand is not None:
                    try:
                        sc_reward_rub += float(grand)
                    except (TypeError, ValueError):
                        pass
                else:
                    for m in milestones:
                        try:
                            sc_reward_rub += float(m.get("rewardRub") or 0)
                        except (TypeError, ValueError):
                            pass
                    try:
                        months = len(scd.get("monthlyBreakdown") or [])
                        sc_reward_rub += float(scd.get("fixedSalaryMonthly") or 0) * months
                    except (TypeError, ValueError):
                        pass
            else:
                for m in milestones:
                    try:
                        sc_reward_rub += float(m.get("rewardRub") or 0)
                    except (TypeError, ValueError):
                        pass
                    try:
                        sc_reward_coins += float(m.get("coins") or 0)
                    except (TypeError, ValueError):
                        pass

        st = p.status or "draft"
        by_status[st] = by_status.get(st, 0) + 1

        pt = p.project_type or "investment"
        by_type[pt] = by_type.get(pt, 0) + 1

        metrics = p.metrics or {}
        if metrics and pt == "investment" and st != "rejected":
            npv = metrics.get("npv", 0) or 0
            total_npv += npv
            irr = metrics.get("irr")
            if irr is not None:
                irr_values.append(float(irr))

        risks = p.risks_data or {}
        if risks:
            ai = risks.get("ai_assessment") or {}
            if ai.get("risk_level") == "высокий":
                high_risk_count += 1
                continue
            if risks.get("overall_risk") == "высокий":
                high_risk_count += 1

    avg_irr = round(sum(irr_values) / len(irr_values), 2) if irr_values else None

    investment_budget = settings_store.get_investment_budget()
    project_ids = [p.id for p in projects]
    approved_investment = 0.0
    if project_ids:
        approved_tranches = (
            db.query(Tranche)
            .filter(Tranche.project_id.in_(project_ids), Tranche.status == "approved")
            .all()
        )
        approved_investment = sum(t.amount for t in approved_tranches)
    available_for_investment = (
        (investment_budget - approved_investment) if investment_budget is not None else None
    )

    return {
        "total": len(projects),
        "by_status": by_status,
        "by_type": by_type,
        "total_npv": round(total_npv, 2),
        "avg_irr": avg_irr,
        "high_risk_count": high_risk_count,
        "investment_budget": investment_budget,
        "approved_investment": round(approved_investment, 2),
        "available_for_investment": round(available_for_investment, 2)
        if available_for_investment is not None
        else None,
        "total_approved_investments": round(approved_investment, 2),
        "ai_active": bool(
            settings_store.get_openai_key()
            or settings_store.get_anthropic_key()
            or settings_store.get_routerai_key()
        ),
        "ai_provider": settings_store.get_ai_provider(),
        "ai_model": ai_model_label(),
        "nav_rate": nav_rate,
        "sc_reward_rub": round(sc_reward_rub, 2),
        "sc_reward_coins": round(sc_reward_coins, 2),
    }
