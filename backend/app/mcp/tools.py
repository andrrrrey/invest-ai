"""
Разрешённые операции ИИ над данными (только чтение на Этапе 2).

Каждая функция принимает сессию БД и возвращает JSON-сериализуемый результат.
Операции на запись появятся на Этапе 4 под отдельным сервис-аккаунтом.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.fact_entry import FactEntry
from ..services import portfolio_service


def _project_brief(p: Project) -> dict:
    metrics = p.metrics or {}
    return {
        "id": p.id,
        "name": p.name,
        "project_type": p.project_type or "investment",
        "status": p.status or "draft",
        "business_unit": p.business_unit,
        "owner": p.owner,
        "npv": metrics.get("npv"),
        "irr": metrics.get("irr"),
    }


def list_projects(
    db: Session,
    status: Optional[str] = None,
    project_type: Optional[str] = None,
) -> dict:
    """Список проектов с краткими показателями (с опциональной фильтрацией)."""
    q = db.query(Project)
    if status:
        q = q.filter(Project.status == status)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    rows = q.order_by(Project.id.desc()).all()
    return {"count": len(rows), "projects": [_project_brief(p) for p in rows]}


def get_project(db: Session, project_id: int) -> dict:
    """Детали одного проекта: статус, метрики, уровень риска, история статусов."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    metrics = p.metrics or {}
    risks = p.risks_data or {}
    scd = p.smart_contract_data or {}
    return {
        "id": p.id,
        "name": p.name,
        "project_type": p.project_type or "investment",
        "status": p.status or "draft",
        "business_unit": p.business_unit,
        "owner": p.owner,
        "stage": p.stage,
        "description": p.description,
        "metrics": {
            k: metrics.get(k) for k in ("npv", "irr", "dpp", "ltvCac", "pi")
        }
        if metrics
        else {},
        "risk_level": (risks.get("ai_assessment") or {}).get("risk_level")
        or risks.get("overall_risk"),
        "milestones_count": len(scd.get("milestones") or []),
        "status_history": p.status_history or [],
    }


def get_portfolio_stats(db: Session, project_type: Optional[str] = None) -> dict:
    """Агрегированные показатели портфеля (счётчики, NPV, IRR, бюджет и т.д.)."""
    return portfolio_service.compute_stats(db, project_type=project_type, user=None)


def list_pending_approvals(db: Session) -> dict:
    """Проекты, ожидающие согласования (статус pending_approval)."""
    rows = (
        db.query(Project)
        .filter(Project.status == "pending_approval")
        .order_by(Project.id.desc())
        .all()
    )
    return {"count": len(rows), "pending": [_project_brief(p) for p in rows]}


def get_project_facts(db: Session, project_id: int) -> dict:
    """Фактические показатели проекта (план/факт/отклонение)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    rows = db.query(FactEntry).filter(FactEntry.project_id == project_id).all()
    facts = []
    for e in rows:
        pv, fv = e.plan_value, e.fact_value
        dev = (
            round((fv - pv) / pv * 100, 1)
            if (pv not in (None, 0) and fv is not None)
            else None
        )
        facts.append(
            {
                "metric": e.metric_name,
                "year": e.year,
                "month": e.month,
                "plan": pv,
                "fact": fv,
                "deviation_pct": dev,
            }
        )
    return {"project_id": project_id, "count": len(facts), "facts": facts}


def get_milestones(db: Session, project_id: int) -> dict:
    """Майлстоуны смарт-контракта: статус, дедлайн, вознаграждение."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    scd = p.smart_contract_data or {}
    milestones = [
        {
            "title": m.get("title") or m.get("name"),
            "status": m.get("status"),
            "deadline": m.get("deadline"),
            "rewardRub": m.get("rewardRub"),
            "coins": m.get("coins"),
        }
        for m in (scd.get("milestones") or [])
        if isinstance(m, dict)
    ]
    return {"project_id": project_id, "count": len(milestones), "milestones": milestones}
