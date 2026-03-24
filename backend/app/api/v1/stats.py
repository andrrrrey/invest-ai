from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.project import Project
from ...models.user import User
from ...auth import get_current_user
from ... import settings_store

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregated portfolio stats for the dashboard.
    Owners see stats only for their own projects.
    """
    q = db.query(Project)
    if current_user.role == "owner":
        q = q.filter(Project.user_id == current_user.id)
    projects = q.all()

    by_status = {"draft": 0, "pending_approval": 0, "approved": 0, "rejected": 0}
    by_type = {"investment": 0, "operational": 0}
    total_npv = 0.0
    irr_values = []
    high_risk_count = 0

    for p in projects:
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

    # Investment budget and approved amount
    investment_budget = settings_store.get_investment_budget()
    approved_investment = 0.0
    for p in projects:
        if p.status == "approved":
            fm = p.financial_model or {}
            try:
                capex = abs(float(fm.get("initialInvestment") or 0))
                approved_investment += capex
            except (TypeError, ValueError):
                pass
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
    }
