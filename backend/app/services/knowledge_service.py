"""
Сервис базы знаний Hermes — «дообучение» бота новыми знаниями.

CRUD над записями (``KnowledgeEntry``), семантический поиск по эмбеддингам с
косинусной близостью и фолбэком на keyword-поиск (SQL LIKE), а также сборка
блока «закреплённых» (pinned) знаний для системного промпта агента.

Вектор эмбеддинга считается при создании/изменении записи (``reindex``). Если
эмбеддинги недоступны (нет ключа, AI выключен, ошибка API) — запись сохраняется
без вектора и остаётся доступной keyword-поиску; поиск тоже мягко деградирует.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.knowledge import KnowledgeEntry
from . import ai_service

logger = logging.getLogger("hermes.knowledge")

# Ниже этого порога косинусной близости совпадение считаем нерелевантным.
_SIM_THRESHOLD = 0.25
# Максимум символов блока закреплённых знаний в системном промпте.
_PINNED_MAX_CHARS = 4000
# Длина фрагмента (snippet) записи в результатах поиска.
_SNIPPET_CHARS = 600


def _to_dict(e: KnowledgeEntry) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "content": e.content,
        "tags": e.tags or [],
        "pinned": bool(e.pinned),
        "is_active": bool(e.is_active),
        "has_embedding": bool(e.embedding),
        "embedding_model": e.embedding_model,
        "created_by": e.created_by,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _embed_input(title: str, content: str) -> str:
    """Текст, по которому считается эмбеддинг записи (заголовок + контент)."""
    return f"{(title or '').strip()}\n{(content or '').strip()}".strip()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_entries(
    db: Session,
    *,
    q: Optional[str] = None,
    pinned: Optional[bool] = None,
    active: Optional[bool] = None,
) -> list[dict]:
    query = db.query(KnowledgeEntry)
    if active is not None:
        query = query.filter(KnowledgeEntry.is_active == active)
    if pinned is not None:
        query = query.filter(KnowledgeEntry.pinned == pinned)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(KnowledgeEntry.title.ilike(like), KnowledgeEntry.content.ilike(like))
        )
    rows = query.order_by(KnowledgeEntry.pinned.desc(), KnowledgeEntry.id.desc()).all()
    return [_to_dict(e) for e in rows]


def get_entry(db: Session, entry_id: int) -> Optional[KnowledgeEntry]:
    return db.get(KnowledgeEntry, entry_id)


def create_entry(
    db: Session,
    *,
    title: str,
    content: str,
    tags: Optional[list] = None,
    pinned: bool = False,
    created_by: Optional[str] = None,
) -> KnowledgeEntry:
    entry = KnowledgeEntry(
        title=title.strip(),
        content=content.strip(),
        tags=list(tags or []),
        pinned=bool(pinned),
        is_active=True,
        created_by=created_by,
    )
    db.add(entry)
    db.flush()  # получить id до reindex
    reindex(db, entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_entry(
    db: Session,
    entry: KnowledgeEntry,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[list] = None,
    pinned: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> KnowledgeEntry:
    content_changed = False
    if title is not None and title.strip() != entry.title:
        entry.title = title.strip()
        content_changed = True
    if content is not None and content.strip() != entry.content:
        entry.content = content.strip()
        content_changed = True
    if tags is not None:
        entry.tags = list(tags)
    if pinned is not None:
        entry.pinned = bool(pinned)
    if is_active is not None:
        entry.is_active = bool(is_active)
    if content_changed:
        reindex(db, entry)
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry: KnowledgeEntry) -> None:
    db.delete(entry)
    db.commit()


# ── Индексация (эмбеддинги) ─────────────────────────────────────────────────────

def reindex(db: Session, entry: KnowledgeEntry) -> bool:
    """Пересчитать эмбеддинг записи. Не фатально при недоступности эмбеддингов —
    вектор просто очищается, запись остаётся доступной keyword-поиску.

    Возвращает True, если вектор посчитан."""
    try:
        vectors = ai_service.embed_texts([_embed_input(entry.title, entry.content)])
    except ai_service.EmbeddingsUnavailable as exc:
        logger.info("Эмбеддинг записи знаний не посчитан (недоступно): %s", exc)
        entry.embedding = None
        entry.embedding_model = None
        return False
    except Exception:
        logger.exception("Ошибка при вычислении эмбеддинга записи знаний")
        entry.embedding = None
        entry.embedding_model = None
        return False
    if vectors:
        from .. import settings_store
        entry.embedding = vectors[0]
        entry.embedding_model = settings_store.get_embedding_model()
        return True
    return False


def reindex_all(db: Session) -> dict:
    """Пересчитать эмбеддинги всех активных записей (после смены модели)."""
    entries = db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).all()  # noqa: E712
    ok = 0
    for e in entries:
        if reindex(db, e):
            ok += 1
    db.commit()
    return {"total": len(entries), "indexed": ok}


# ── Поиск ───────────────────────────────────────────────────────────────────────

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _snippet(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + "…"


def _keyword_search(db: Session, query: str, top_k: int) -> list[dict]:
    like = f"%{query.strip()}%"
    rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.is_active == True)  # noqa: E712
        .filter(or_(KnowledgeEntry.title.ilike(like), KnowledgeEntry.content.ilike(like)))
        .order_by(KnowledgeEntry.pinned.desc(), KnowledgeEntry.id.desc())
        .limit(top_k)
        .all()
    )
    return [
        {"id": e.id, "title": e.title, "snippet": _snippet(e.content),
         "tags": e.tags or [], "score": None, "match": "keyword"}
        for e in rows
    ]


def search(db: Session, query: str, top_k: int = 5) -> list[dict]:
    """Найти релевантные знания под вопрос пользователя.

    Сначала пробуем семантический поиск (эмбеддинг запроса + косинусная близость
    к записям с вектором). При недоступности эмбеддингов или отсутствии
    проиндексированных записей — фолбэк на keyword-поиск (SQL ILIKE).
    """
    query = (query or "").strip()
    if not query:
        return []

    indexed = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.is_active == True)  # noqa: E712
        .filter(KnowledgeEntry.embedding.isnot(None))
        .all()
    )
    if not indexed:
        return _keyword_search(db, query, top_k)

    try:
        q_vec = ai_service.embed_texts([query])[0]
    except ai_service.EmbeddingsUnavailable as exc:
        logger.info("Семантический поиск недоступен, keyword-фолбэк: %s", exc)
        return _keyword_search(db, query, top_k)
    except Exception:
        logger.exception("Ошибка эмбеддинга запроса, keyword-фолбэк")
        return _keyword_search(db, query, top_k)

    q_arr = np.asarray(q_vec, dtype=float)
    scored = []
    for e in indexed:
        try:
            sim = _cosine(q_arr, np.asarray(e.embedding, dtype=float))
        except Exception:
            continue
        if sim >= _SIM_THRESHOLD:
            scored.append((sim, e))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = [
        {"id": e.id, "title": e.title, "snippet": _snippet(e.content),
         "tags": e.tags or [], "score": round(sim, 4), "match": "semantic"}
        for sim, e in scored[:top_k]
    ]
    # Если по семантике ничего не прошло порог — подстрахуемся keyword-поиском.
    return results or _keyword_search(db, query, top_k)


# ── Промпт агента ─────────────────────────────────────────────────────────────

def pinned_block(db: Session, max_chars: int = _PINNED_MAX_CHARS) -> str:
    """Собрать текст закреплённых знаний для системного промпта Hermes."""
    rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.is_active == True)  # noqa: E712
        .filter(KnowledgeEntry.pinned == True)  # noqa: E712
        .order_by(KnowledgeEntry.id.asc())
        .all()
    )
    parts = []
    total = 0
    for e in rows:
        line = f"- {e.title.strip()}: {e.content.strip()}"
        if total + len(line) > max_chars:
            remaining = max_chars - total
            if remaining > 40:
                parts.append(line[:remaining] + "…")
            break
        parts.append(line)
        total += len(line) + 1
    return "\n".join(parts)
