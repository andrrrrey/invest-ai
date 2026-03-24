"""
Export API — POST /api/v1/export/
Generates a PDF or Excel management report for the portfolio.
Accessible to CEO, CFO, manager (owner role is blocked via require_not_owner).
"""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.project import Project
from ...models.user import User
from ...auth import require_not_owner
from ... import settings_store
from ...services import ai_service
from ...services.export_excel import build_excel
from ...services.export_pdf import build_pdf

router = APIRouter(prefix="/export", tags=["export"])


class ExportRequest(BaseModel):
    format: Literal["pdf", "excel"]
    project_ids: list[int] | None = None   # None = all projects
    period_label: str = "Весь период"
    detail_level: Literal["summary", "full"] = "summary"
    include_ai: bool = False


def _compute_stats(projects: list[Project]) -> dict:
    """Compute portfolio stats from a list of Project ORM objects."""
    by_status = {"draft": 0, "pending_approval": 0, "approved": 0, "rejected": 0}
    by_type   = {"investment": 0, "operational": 0}
    total_npv = 0.0
    irr_values: list[float] = []
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

    investment_budget   = settings_store.get_investment_budget()
    approved_investment = 0.0
    for p in projects:
        if p.status == "approved":
            fm = p.financial_model or {}
            try:
                capex = abs(float(fm.get("initialInvestment") or 0))
                approved_investment += capex
            except (TypeError, ValueError):
                pass

    available = (
        (investment_budget - approved_investment) if investment_budget is not None else None
    )

    return {
        "total":               len(projects),
        "by_status":           by_status,
        "by_type":             by_type,
        "total_npv":           round(total_npv, 2),
        "avg_irr":             avg_irr,
        "high_risk_count":     high_risk_count,
        "investment_budget":   investment_budget,
        "approved_investment": round(approved_investment, 2),
        "available_for_investment": round(available, 2) if available is not None else None,
    }


def _project_to_dict(p: Project) -> dict:
    return {
        "id":             p.id,
        "name":           p.name,
        "business_unit":  p.business_unit,
        "description":    p.description,
        "owner":          p.owner,
        "stage":          p.stage,
        "start_date":     str(p.start_date) if p.start_date else None,
        "project_type":   p.project_type,
        "financial_model": p.financial_model,
        "metrics":        p.metrics,
        "risks_data":     p.risks_data,
        "value_score_data": p.value_score_data,
        "status":         p.status,
        "decision_route": p.decision_route,
    }


@router.post("/")
def export_report(
    req: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_not_owner),
):
    # Load projects
    q = db.query(Project)
    if req.project_ids:
        q = q.filter(Project.id.in_(req.project_ids))
    projects_orm = q.order_by(Project.created_at.desc()).all()

    if not projects_orm:
        raise HTTPException(status_code=404, detail="Проекты не найдены")

    projects = [_project_to_dict(p) for p in projects_orm]
    stats    = _compute_stats(projects_orm)

    # AI generation (optional)
    portfolio_commentary = ""
    ai_commentaries: dict[int, str] = {}

    if req.include_ai:
        try:
            portfolio_commentary = ai_service.generate_portfolio_commentary(projects, stats)
        except Exception:
            portfolio_commentary = ""

        for p in projects:
            try:
                result = ai_service.analyze_project(p, p.get("metrics") or {})
                comment = result.get("comment", "")
                ai_commentaries[p["id"]] = comment
            except Exception:
                ai_commentaries[p["id"]] = ""

    # Build and return the file
    if req.format == "excel":
        buf = build_excel(
            projects=projects,
            stats=stats,
            detail_level=req.detail_level,
            include_ai=req.include_ai,
            ai_commentaries=ai_commentaries,
            period_label=req.period_label,
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename   = "report.xlsx"
    else:
        buf = build_pdf(
            projects=projects,
            stats=stats,
            detail_level=req.detail_level,
            include_ai=req.include_ai,
            portfolio_commentary=portfolio_commentary,
            ai_commentaries=ai_commentaries,
            period_label=req.period_label,
            generated_by=current_user.full_name or current_user.username,
        )
        media_type = "application/pdf"
        filename   = "report.pdf"

    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
