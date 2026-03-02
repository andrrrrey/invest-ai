from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ...database import get_db
from ...models.project import Project
from ...schemas.project import ProjectCreate, ProjectUpdate, ProjectRead
from ...schemas.finance import FinancialModelInput
from ...services.finance_service import calculate_metrics

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


@router.get("/", response_model=List[ProjectRead])
def list_projects(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Project)
    if status:
        q = q.filter(Project.status == status)
    return q.order_by(Project.created_at.desc()).all()


@router.post("/", response_model=ProjectRead, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**data.model_dump())
    db.add(project)
    db.flush()  # get id before metrics calc
    _recalc_and_save(project, db)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in data.model_dump(exclude_unset=True).items():
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
):
    """Change project status: draft → pending_approval → approved/rejected."""
    allowed = {"draft", "pending_approval", "approved", "rejected"}
    new_status = body.get("status")
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {allowed}")

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = new_status
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
