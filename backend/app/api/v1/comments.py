from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.comment import Comment
from ...models.project import Project
from ...auth import get_current_user

router = APIRouter(tags=["comments"])


class CommentCreate(BaseModel):
    text: str


class CommentRead(BaseModel):
    id: int
    text: str
    created_at: datetime
    author_name: str

    class Config:
        from_attributes = True


@router.get("/projects/{project_id}/comments", response_model=List[CommentRead])
def list_comments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    rows = (
        db.query(Comment)
        .filter(Comment.project_id == project_id)
        .order_by(Comment.created_at.desc())
        .all()
    )
    return [
        CommentRead(
            id=c.id,
            text=c.text,
            created_at=c.created_at,
            author_name=c.author.full_name if c.author else "—",
        )
        for c in rows
    ]


@router.post("/projects/{project_id}/comments", response_model=CommentRead, status_code=201)
def create_comment(
    project_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Комментарий не может быть пустым")
    c = Comment(project_id=project_id, user_id=current_user.id, text=body.text.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    return CommentRead(
        id=c.id,
        text=c.text,
        created_at=c.created_at,
        author_name=current_user.full_name,
    )
