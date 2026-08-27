from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List

from ...database import get_db
from ...models.project import Project
from ...models.user import User
from ...schemas.project import ProjectCreate, ProjectUpdate, ProjectRead
from ...schemas.finance import FinancialModelInput
from ...services.finance_service import calculate_metrics
from ...auth import get_current_user
from ...services.email_service import (
    send_approval_request_emails,
    send_status_notification_email,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _monthly_to_quarterly(monthly: list, num_years: int) -> list:
    """Convert a [year][month] users table to [year][quarter] by summing months."""
    result = []
    for y in range(num_years):
        year_data = monthly[y] if y < len(monthly) else []
        row = []
        for q in range(4):
            ms = [year_data[3*q + m] if 3*q + m < len(year_data) else 0 for m in range(3)]
            row.append(sum(ms))
        result.append(row)
    return result


def _recalc_and_save(project: Project, db: Session) -> None:
    """Recalculate financial metrics and persist them."""
    import logging
    _log = logging.getLogger(__name__)

    fm = project.financial_model
    if not fm:
        return
    try:
        # The frontend stores the entire form inside financial_model,
        # which may include empty-string values for numeric fields
        # (e.g. nwc: '').  Sanitise known numeric fields so that
        # Pydantic validation does not fail silently.
        clean = dict(fm)
        for key in ("nwc", "initialInvestment", "keyRate", "riskPremium",
                     "conversionRate", "churnRate", "quarterlyChurnIncrease",
                     "indexationRate", "numYears"):
            val = clean.get(key)
            if val is None or val == "":
                clean.pop(key, None)          # let Pydantic use the default

        # granularity and usersMonthly are now passed directly to the calculation
        # engine which handles monthly granularity internally.
        model_input = FinancialModelInput(**clean)
        metrics = calculate_metrics(model_input)
        project.metrics = metrics.model_dump()
    except Exception:
        _log.exception("Failed to recalculate metrics for project %s", project.id)


def _get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project


def _check_project_access(project: Project, current_user: User):
    """Owner can only access their own projects."""
    if current_user.role == "owner" and project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому проекту",
        )


def get_accessible_project(project_id: int, db: Session, current_user: User) -> Project:
    """Load a project by id (404 if missing) and enforce access control.

    Reusable across all nested resource endpoints (attachments, comments,
    tranches, fact, export) so that an owner cannot reach another owner's
    project via a direct id (IDOR).
    """
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)
    return project


@router.get("/", response_model=List[ProjectRead])
def list_projects(
    status: str | None = None,
    project_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Project)
    # Owners see only their own projects, except approved projects are visible system-wide
    if current_user.role == "owner" and status != "approved":
        q = q.filter(Project.user_id == current_user.id)
    if status:
        q = q.filter(Project.status == status)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    else:
        # Smart contracts live in the same table but have their own dedicated
        # section. They must never leak into the general projects list.
        # (NULL project_type means a legacy investment project — keep it.)
        q = q.filter(
            or_(
                Project.project_type.is_(None),
                Project.project_type != "smart_contract",
            )
        )
    return q.order_by(Project.created_at.desc()).all()


@router.post("/", response_model=ProjectRead, status_code=201)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # CEO cannot create projects
    if current_user.role == "ceo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CEO не может создавать проекты",
        )

    project_data = data.model_dump()
    # Auto-assign owner from current user
    project_data["user_id"] = current_user.id
    if not project_data.get("owner"):
        project_data["owner"] = current_user.full_name

    project = Project(**project_data)
    db.add(project)
    db.flush()
    _recalc_and_save(project, db)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)
    return project


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)

    # CEO cannot edit projects
    if current_user.role == "ceo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CEO не может редактировать проекты",
        )
    # Owner can only edit their own draft or pending_approval projects
    if current_user.role == "owner" and project.status not in ("draft", "pending_approval"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Заявитель может редактировать только черновики и заявки на согласовании",
        )

    update_data = data.model_dump(exclude_unset=True)
    # Never allow changing the ownership via update
    update_data.pop("user_id", None)

    for field, value in update_data.items():
        setattr(project, field, value)

    _recalc_and_save(project, db)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/status", response_model=ProjectRead)
def change_status(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change project status with role-based permission checks."""
    allowed_statuses = {"draft", "pending_approval", "approved", "rejected", "rework_needed"}
    new_status = body.get("status")
    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый статус. Разрешены: {allowed_statuses}",
        )

    project = _get_project_or_404(project_id, db)

    # Единая логика смены статуса (права, история, уведомления, карточки
    # согласования в Mattermost, аудит) — та же, что и для нажатий кнопок.
    from ...services import approval_service
    return approval_service.apply_status_change(db, project, new_status, current_user)


@router.patch("/{project_id}/recalculate", response_model=ProjectRead)
def recalculate_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force-recalculate and persist financial metrics without touching any
    other project fields.  Available to CFO and Manager for all projects;
    Owner can recalculate only their own projects."""
    project = _get_project_or_404(project_id, db)
    _check_project_access(project, current_user)

    if current_user.role not in ("cfo", "manager", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для пересчёта метрик",
        )

    _recalc_and_save(project, db)
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/copy", response_model=ProjectRead, status_code=201)
def copy_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a draft copy of an existing project."""
    if current_user.role == "ceo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CEO не может создавать проекты",
        )

    source = _get_project_or_404(project_id, db)
    _check_project_access(source, current_user)

    import copy as _copy
    new_project = Project(
        name="Копия: " + (source.name or ""),
        project_type=source.project_type,
        status="draft",
        description=source.description,
        owner=current_user.full_name or source.owner,
        start_date=source.start_date,
        platform=source.platform,
        stage=source.stage,
        business_unit=source.business_unit,
        financial_model=_copy.deepcopy(source.financial_model) if source.financial_model else None,
        user_id=current_user.id,
    )
    db.add(new_project)
    db.flush()
    _recalc_and_save(new_project, db)
    db.commit()
    db.refresh(new_project)
    return new_project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project_or_404(project_id, db)

    role = current_user.role
    # CEO is an observer — never deletes.
    if role == "ceo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для удаления проекта",
        )
    # Applicant (owner) may delete only their OWN draft.
    if role == "owner" and (
        project.user_id != current_user.id or (project.status or "draft") != "draft"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Заявитель может удалять только собственные черновики",
        )
    # CFO and Manager may delete any project.

    db.delete(project)
    db.commit()
