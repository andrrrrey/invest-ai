"""Проект приказа (ЛНА) по согласованному контракту / проекту."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models.user import User
from ...services import order_service
from .projects import get_accessible_project

router = APIRouter(prefix="/projects", tags=["orders"])

ORDER_PROJECT_TYPES = ("smart_contract",)


def _project(db: Session, project_id: int, user: User):
    project = get_accessible_project(project_id, db, user)
    if (project.project_type or "investment") not in ORDER_PROJECT_TYPES:
        raise HTTPException(status_code=400, detail="Для этого типа проекта приказ не формируется")
    return project


@router.get("/{project_id}/order")
def get_order(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _project(db, project_id, current_user)
    return order_service.order_state(db, project, current_user)


@router.post("/{project_id}/order")
def generate_order(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Сформировать проект приказа (.docx) и отправить на согласование C&B → юрист → CEO."""
    project = _project(db, project_id, current_user)
    order_service.generate(db, project, current_user)
    db.refresh(project)
    return order_service.order_state(db, project, current_user)


@router.post("/{project_id}/order/upload")
async def upload_order(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Загрузить исправленный проект приказа и запустить согласование заново."""
    project = _project(db, project_id, current_user)
    content = await file.read()
    order_service.upload_revision(db, project, current_user, content, file.filename or "Приказ.docx")
    db.refresh(project)
    return order_service.order_state(db, project, current_user)
