"""
Разрешённые операции ИИ над данными (только чтение на Этапе 2).

Каждая функция принимает сессию БД и возвращает JSON-сериализуемый результат.
Операции на запись появятся на Этапе 4 под отдельным сервис-аккаунтом.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.fact_entry import FactEntry
from ..services import portfolio_service, write_service, links


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
        "url": links.project_url(p.project_type, p.id),
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


def find_projects(db: Session, query: str) -> dict:
    """Найти проекты по части названия (регистронезависимо).

    Возвращает краткие карточки со ссылками — чтобы обращаться к проекту по
    названию, не зная числового id.
    """
    q = (query or "").strip()
    if not q:
        return {"count": 0, "projects": [], "note": "Пустой запрос поиска"}
    # Регистронезависимый поиск делаем в Python: встроенный lower() в SQLite не
    # понижает регистр кириллицы, поэтому SQL LIKE был бы ненадёжен.
    needle = q.lower()
    rows = [
        p for p in db.query(Project).order_by(Project.id.desc()).all()
        if p.name and needle in p.name.lower()
    ]
    return {"count": len(rows), "query": q, "projects": [_project_brief(p) for p in rows]}


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
        "url": links.project_url(p.project_type, p.id),
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


_DONE_MILESTONE_STATUSES = {"paid", "done", "completed"}


def _parse_deadline(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def list_upcoming_deadlines(db: Session, window_days: int = 30) -> dict:
    """Сроки по проектам: незавершённые майлстоуны с приближающимися или
    просроченными дедлайнами (для аналитики по срокам действующих проектов).

    Возвращает список, отсортированный по дедлайну, с флагом просрочки и
    числом дней до дедлайна.
    """
    try:
        window_days = int(window_days)
    except (TypeError, ValueError):
        window_days = 30
    today = _dt.date.today()
    horizon = today + _dt.timedelta(days=window_days)

    projects = (
        db.query(Project)
        .filter(Project.project_type == "smart_contract")
        .all()
    )
    items = []
    for p in projects:
        scd = p.smart_contract_data or {}
        for m in scd.get("milestones") or []:
            if not isinstance(m, dict):
                continue
            if (m.get("status") or "").lower() in _DONE_MILESTONE_STATUSES:
                continue
            deadline = _parse_deadline(m.get("deadline"))
            if not deadline:
                continue
            # Просроченные и попадающие в окно — всё, что <= горизонта.
            if deadline <= horizon:
                items.append({
                    "project_id": p.id,
                    "project": p.name,
                    "milestone": m.get("title") or m.get("name"),
                    "status": m.get("status"),
                    "deadline": deadline.isoformat(),
                    "days_left": (deadline - today).days,
                    "overdue": deadline < today,
                })
    items.sort(key=lambda x: x["deadline"])
    return {
        "window_days": window_days,
        "count": len(items),
        "overdue_count": sum(1 for i in items if i["overdue"]),
        "deadlines": items,
    }


# ── Операции на запись (Этап 4, включаются флагом hermes_write_enabled) ────────

def update_fact(db: Session, project_id: int, entries: list) -> dict:
    """Обновить фактические/плановые значения по метрикам проекта."""
    return write_service.update_fact(db, project_id, entries, actor_type="hermes")


def update_milestone_status(db: Session, project_id: int, index: int, status: str) -> dict:
    """Изменить статус майлстоуна смарт-контракта."""
    return write_service.update_milestone_status(
        db, project_id, index, status, actor_type="hermes"
    )
