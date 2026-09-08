"""
База знаний Hermes — «дообучение» бота новыми знаниями (только CFO).

CRUD над записями знаний, которые Hermes учитывает в ответах: закреплённые
(pinned) знания попадают в системный промпт, вся активная база доступна через
инструмент ``search_knowledge`` (семантический поиск + keyword-фолбэк).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth import require_cfo
from ...database import get_db
from ...schemas.knowledge import KnowledgeCreate, KnowledgeUpdate, KnowledgeSearchRequest
from ...services import knowledge_service, audit_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _entry_out(e) -> dict:
    return knowledge_service._to_dict(e)


@router.get("/")
def list_knowledge(
    q: Optional[str] = None,
    pinned: Optional[bool] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _=Depends(require_cfo),
):
    """Список записей знаний (с фильтрами по тексту/закреплению/активности)."""
    return {"items": knowledge_service.list_entries(db, q=q, pinned=pinned, active=active)}


@router.post("/")
def create_knowledge(
    body: KnowledgeCreate,
    db: Session = Depends(get_db),
    user=Depends(require_cfo),
):
    entry = knowledge_service.create_entry(
        db,
        title=body.title,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        created_by=getattr(user, "email", None),
    )
    audit_service.log_event(
        action="knowledge.create",
        actor_type="user",
        actor_id=getattr(user, "email", None),
        target_type="knowledge",
        target_id=str(entry.id),
        meta={"pinned": entry.pinned, "indexed": bool(entry.embedding)},
    )
    return _entry_out(entry)


@router.put("/{entry_id}")
def update_knowledge(
    entry_id: int,
    body: KnowledgeUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_cfo),
):
    entry = knowledge_service.get_entry(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись знаний не найдена.")
    entry = knowledge_service.update_entry(
        db,
        entry,
        title=body.title,
        content=body.content,
        tags=body.tags,
        pinned=body.pinned,
        is_active=body.is_active,
    )
    audit_service.log_event(
        action="knowledge.update",
        actor_type="user",
        actor_id=getattr(user, "email", None),
        target_type="knowledge",
        target_id=str(entry.id),
        meta={"pinned": entry.pinned, "is_active": entry.is_active},
    )
    return _entry_out(entry)


@router.delete("/{entry_id}")
def delete_knowledge(
    entry_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_cfo),
):
    entry = knowledge_service.get_entry(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись знаний не найдена.")
    knowledge_service.delete_entry(db, entry)
    audit_service.log_event(
        action="knowledge.delete",
        actor_type="user",
        actor_id=getattr(user, "email", None),
        target_type="knowledge",
        target_id=str(entry_id),
    )
    return {"success": True}


@router.post("/reindex")
def reindex_knowledge(
    db: Session = Depends(get_db),
    user=Depends(require_cfo),
):
    """Пересчитать эмбеддинги всех активных записей (после смены модели)."""
    result = knowledge_service.reindex_all(db)
    audit_service.log_event(
        action="knowledge.reindex",
        actor_type="user",
        actor_id=getattr(user, "email", None),
        meta=result,
    )
    return result


@router.post("/search")
def search_knowledge(
    body: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    _=Depends(require_cfo),
):
    """Тестовый поиск по базе знаний (проверка из UI)."""
    top_k = max(1, min(body.top_k or 5, 10))
    return {"results": knowledge_service.search(db, body.query, top_k=top_k)}
