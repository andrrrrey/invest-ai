"""
Операции на запись через помощника (Этап 4) — рутина заявителя.

Обновление фактических показателей и статуса майлстоунов. Это НЕ решения за
людей (согласование остаётся за CFO/менеджером через карточки) — только
поддержание данных в актуальном состоянии. Каждое действие фиксируется в
аудите (``write.fact`` / ``write.milestone``).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.fact_entry import FactEntry
from ..models.project import Project
from . import audit_service

logger = logging.getLogger("hermes.write")

# Разрешённые статусы майлстоуна (совпадают с фронтендом smart-contract).
MILESTONE_STATUSES = {"pending", "in_progress", "verify", "paid", "disputed"}


def update_fact(
    db: Session,
    project_id: int,
    entries: List[dict],
    *,
    actor_type: str = "user",
    actor_id: Optional[str] = None,
) -> dict:
    """Upsert фактических/плановых значений по метрикам проекта.

    ``entries``: список ``{year, month, metric_name, plan_value?, fact_value?}``.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    updated = 0
    for item in entries or []:
        try:
            year = int(item["year"])
            month = int(item["month"])
            metric_name = str(item["metric_name"])
        except (KeyError, TypeError, ValueError):
            continue
        existing = (
            db.query(FactEntry)
            .filter_by(project_id=project_id, year=year, month=month, metric_name=metric_name)
            .first()
        )
        if existing:
            if item.get("plan_value") is not None:
                existing.plan_value = item["plan_value"]
            if item.get("fact_value") is not None:
                existing.fact_value = item["fact_value"]
        else:
            db.add(
                FactEntry(
                    project_id=project_id,
                    year=year,
                    month=month,
                    metric_name=metric_name,
                    plan_value=item.get("plan_value"),
                    fact_value=item.get("fact_value"),
                )
            )
        updated += 1

    db.commit()
    audit_service.log_event(
        action="write.fact",
        actor_type=actor_type,
        actor_id=actor_id,
        result="ok",
        target_type="project",
        target_id=str(project_id),
        meta={"entries": updated},
    )
    return {"project_id": project_id, "updated": updated}


def update_milestone_status(
    db: Session,
    project_id: int,
    index: int,
    new_status: str,
    *,
    actor_type: str = "user",
    actor_id: Optional[str] = None,
) -> dict:
    """Персистентно изменить статус майлстоуна смарт-контракта.

    Закрывает пробел: раньше статус майлстоуна менялся только в памяти фронта.
    """
    if new_status not in MILESTONE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый статус майлстоуна. Разрешены: {sorted(MILESTONE_STATUSES)}",
        )
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    scd = dict(project.smart_contract_data or {})
    milestones = list(scd.get("milestones") or [])
    if index < 0 or index >= len(milestones):
        raise HTTPException(status_code=404, detail="Майлстоун не найден")

    milestone = dict(milestones[index])
    old_status = milestone.get("status")
    milestone["status"] = new_status
    milestones[index] = milestone
    scd["milestones"] = milestones
    project.smart_contract_data = scd  # переприсваиваем, чтобы ORM увидел мутацию JSON
    db.commit()

    audit_service.log_event(
        action="write.milestone",
        actor_type=actor_type,
        actor_id=actor_id,
        result="ok",
        target_type="project",
        target_id=str(project_id),
        meta={"index": index, "from": old_status, "to": new_status},
    )
    return {
        "project_id": project_id,
        "index": index,
        "status": new_status,
        "title": milestone.get("title") or milestone.get("name"),
    }
