from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.comment import Comment
from ...models.project import Project
from ...auth import get_current_user
from ...services import links, mention_service
from ...services.contract_notifications import notify_user
from .projects import get_accessible_project

router = APIRouter(tags=["comments"])


class CommentCreate(BaseModel):
    text: str


class CommentRead(BaseModel):
    id: int
    text: str
    created_at: datetime
    author_name: str
    mentions: Optional[List[Any]] = None

    class Config:
        from_attributes = True


@router.get("/projects/{project_id}/comments", response_model=List[CommentRead])
def list_comments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    get_accessible_project(project_id, db, current_user)
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
            mentions=c.mentions or [],
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
    project = get_accessible_project(project_id, db, current_user)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Комментарий не может быть пустым")
    text = body.text.strip()
    mentioned = mention_service.parse_mentions(db, text, exclude_user_id=current_user.id)
    c = Comment(
        project_id=project_id, user_id=current_user.id, text=text,
        mentions=[{"id": u.id, "full_name": u.full_name} for u in mentioned],
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    # Упомянутым — уведомление от Баффета со ссылкой прямо на комментарий.
    snippet = text if len(text) <= 300 else text[:297] + "…"
    for u in mentioned:
        notify_user(
            db, u, project=project,
            title=f"{current_user.full_name} упомянул(а) вас в комментарии",
            message=f"{links.label_for(project)} «{project.name or 'без названия'}»: «{snippet}»",
            anchor=f"comment-{c.id}",
        )
    return CommentRead(
        id=c.id,
        text=c.text,
        created_at=c.created_at,
        author_name=current_user.full_name,
        mentions=c.mentions or [],
    )
