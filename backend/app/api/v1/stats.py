from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.project import Project

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/")
def get_stats(db: Session = Depends(get_db)):
    """
    Aggregated portfolio stats for the dashboard.
    Returns counts by status/type, total NPV, avg IRR, and high-risk count.
    """
    projects = db.query(Project).all()

    by_status = {"draft": 0, "pending_approval": 0, "approved": 0, "rejected": 0}
    by_type = {"investment": 0, "operational": 0}
    total_npv = 0.0
    irr_values = []
    high_risk_count = 0

    for p in projects:
        # Status counts
        st = p.status or "draft"
        by_status[st] = by_status.get(st, 0) + 1

        # Type counts
        pt = p.project_type or "investment"
        by_type[pt] = by_type.get(pt, 0) + 1

        # Financial metrics — exclude rejected projects from NPV/IRR totals
        metrics = p.metrics or {}
        if metrics and st != "rejected":
            npv = metrics.get("npv", 0) or 0
            total_npv += npv
            irr = metrics.get("irr")
            if irr is not None:
                irr_values.append(float(irr))

        # High-risk detection
        risks = p.risks_data or {}
        if risks:
            # Investment projects: risks_data.ai_assessment.risk_level
            ai = risks.get("ai_assessment") or {}
            if ai.get("risk_level") == "высокий":
                high_risk_count += 1
                continue
            # Operational projects: risks_data.overall_risk
            if risks.get("overall_risk") == "высокий":
                high_risk_count += 1

    avg_irr = round(sum(irr_values) / len(irr_values), 2) if irr_values else None

    return {
        "total": len(projects),
        "by_status": by_status,
        "by_type": by_type,
        "total_npv": round(total_npv, 2),
        "avg_irr": avg_irr,
        "high_risk_count": high_risk_count,
    }
