from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ...database import get_db
from ...models.project import Project
from ...models.user import User
from ...schemas.project import ProjectCreate, ProjectUpdate, ProjectRead
from ...schemas.finance import FinancialModelInput
from ...services.finance_service import calculate_metrics
from ...auth import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


def _recalc_and_save(project: Project, db: Session) -> None:
    """Recalculate financial metrics and persist them."""
    fm = project.financial_model
    if not fm:
        return
    try:
        model_input = FinancialModelInput(**fm)
        metrics = calculate_metrics(model_input)
        project.metrics = metrics.model_dump()
    except Exception:
        pass


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


@router.get("/", response_model=List[ProjectRead])
def list_projects(
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Project)
    # Owners see only their own projects, except approved projects are visible system-wide
    if current_user.role == "owner" and status != "approved":
        q = q.filter(Project.user_id == current_user.id)
    if status:
        q = q.filter(Project.status == status)
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
    # Owner can only edit their own draft projects
    if current_user.role == "owner" and project.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Заявитель может редактировать только черновики",
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
    allowed_statuses = {"draft", "pending_approval", "approved", "rejected"}
    new_status = body.get("status")
    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый статус. Разрешены: {allowed_statuses}",
        )

    project = _get_project_or_404(project_id, db)

    role = current_user.role

    if new_status in ("approved", "rejected"):
        # Only CFO and Manager can approve/reject
        if role not in ("cfo", "manager"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Только CFO или Менеджер могут согласовывать/отклонять заявки",
            )
    elif new_status == "pending_approval":
        # CEO cannot submit; Owner can only submit their own project
        if role == "ceo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CEO не может подавать заявки на согласование",
            )
        if role == "owner" and project.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому проекту",
            )
    elif new_status == "draft":
        # Return to draft: cfo/manager always, owner only for their own
        if role == "owner" and project.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому проекту",
            )

    project.status = new_status
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project_or_404(project_id, db)

    # CEO and Owner cannot delete
    if current_user.role in ("ceo", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для удаления проекта",
        )

    db.delete(project)
    db.commit()
