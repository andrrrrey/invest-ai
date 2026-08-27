"""
Просмотр журнала аудита (только CFO).

Показывает, что и когда делал помощник и к каким данным обращался ИИ.
Конфиденциальный текст в журнал не пишется — только метаданные и метки.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import require_cfo
from ...database import get_db
from ...models.audit_log import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/")
def list_audit(
    action: Optional[str] = None,
    result: Optional[str] = None,
    actor_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _=Depends(require_cfo),
):
    """Список записей аудита с фильтрами и пагинацией (новые сверху)."""
    limit = max(1, min(limit, 500))
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if result:
        q = q.filter(AuditLog.result == result)
    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)

    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "result": r.result,
                "error_message": r.error_message,
                "ai_provider": r.ai_provider,
                "ai_model": r.ai_model,
                "anonymized": r.anonymized,
                "meta": r.meta,
            }
            for r in rows
        ],
    }
