from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.project import Project
from ...models.tranche import Tranche
from ...models.user import User
from ...auth import get_current_user
from ... import settings_store

router = APIRouter(prefix="/stats", tags=["stats"])

_ROUTERAI_LABELS = {
    "anthropic/claude-sonnet-4.5": "Claude Sonnet 4.5",
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
    "anthropic/claude-opus-4.5": "Claude Opus 4.5",
}


def _ai_model_label() -> str:
    provider = settings_store.get_ai_provider()
    if provider == "anthropic":
        return "Claude Sonnet 4.6"
    if provider == "routerai":
        model = settings_store.get_routerai_model()
        return _ROUTERAI_LABELS.get(model, model)
    return "GPT-5.4"


@router.get("/")
def get_stats(
    project_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregated portfolio stats for the dashboard.
    Owners see stats only for their own projects.
    When project_type is provided, stats are scoped to that type
    (used by the smart-contracts dashboard).
    """
    q = db.query(Project)
    if current_user.role == "owner":
        q = q.filter(Project.user_id == current_user.id)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    projects = q.all()

    by_status = {"draft": 0, "pending_approval": 0, "approved": 0, "rejected": 0}
    by_type = {"investment": 0, "operational": 0}
    total_npv = 0.0
    irr_values = []
    high_risk_count = 0

    # Smart-contract specific aggregates
    sc_reward_rub = 0.0
    sc_reward_coins = 0.0
    nav_rate = settings_store.get_nav_rate()

    for p in projects:
        if (p.project_type or "") == "smart_contract":
            scd = p.smart_contract_data or {}
            milestones = scd.get("milestones") or []
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

    # Investment budget: use approved tranches as committed investment
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
    available_for_investment = (investment_budget - approved_investment) if investment_budget is not None else None

    return {
        "total": len(projects),
        "by_status": by_status,
        "by_type": by_type,
        "total_npv": round(total_npv, 2),
        "avg_irr": avg_irr,
        "high_risk_count": high_risk_count,
        "investment_budget": investment_budget,
        "approved_investment": round(approved_investment, 2),
        "available_for_investment": round(available_for_investment, 2) if available_for_investment is not None else None,
        "total_approved_investments": round(approved_investment, 2),
        "ai_active": bool(
            settings_store.get_openai_key()
            or settings_store.get_anthropic_key()
            or settings_store.get_routerai_key()
        ),
        "ai_provider": settings_store.get_ai_provider(),
        "ai_model": _ai_model_label(),
        "nav_rate": nav_rate,
        "sc_reward_rub": round(sc_reward_rub, 2),
        "sc_reward_coins": round(sc_reward_coins, 2),
    }
