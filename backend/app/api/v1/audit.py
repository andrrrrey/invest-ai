"""
Просмотр журнала аудита (только CFO).

Показывает, что и когда делал помощник и к каким данным обращался ИИ.
Конфиденциальный текст в журнал не пишется — только метаданные и метки.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import require_cfo
from ...config import settings
from ...database import get_db
from ...models.audit_log import AuditLog
from ...services import log_export, email_service, audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


def _filtered_query(db: Session, action, result, actor_type):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if result:
        q = q.filter(AuditLog.result == result)
    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)
    return q


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


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


# ── Системные логи (CFO): предпросмотр / скачивание / отправка ────────────────

@router.get("/logs/preview")
def logs_preview(
    level: Optional[str] = None,
    q: Optional[str] = None,
    lines: int = 200,
    _=Depends(require_cfo),
):
    """Хвост системных логов для предпросмотра на экране (JSON-строки)."""
    text = log_export.read_logs(level=level, contains=q, max_lines=min(lines, 2000))
    return {
        "developer_email": settings.DEVELOPER_EMAIL,
        "count": len([ln for ln in text.split("\n") if ln]) if text else 0,
        "text": text,
    }


@router.get("/logs/download")
def logs_download(
    level: Optional[str] = None,
    q: Optional[str] = None,
    lines: int = 5000,
    _=Depends(require_cfo),
):
    """Скачать отфильтрованные системные логи как файл."""
    text = log_export.read_logs(level=level, contains=q, max_lines=lines)
    filename = f"hermes-logs-{_ts()}.log"
    return Response(
        content=(text or "").encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class LogsEmailRequest(BaseModel):
    to: str
    level: Optional[str] = None
    q: Optional[str] = None
    lines: int = 5000


@router.post("/logs/email")
def logs_email(body: LogsEmailRequest, _=Depends(require_cfo)):
    """Отправить выгрузку логов разработчику вложением."""
    to = (body.to or "").strip()
    if "@" not in to:
        raise HTTPException(status_code=422, detail="Укажите корректный email.")
    text = log_export.read_logs(level=body.level, contains=body.q, max_lines=body.lines)
    if not text:
        raise HTTPException(status_code=404, detail="Логи пусты по заданному фильтру.")
    filename = f"hermes-logs-{_ts()}.log"
    try:
        email_service.send_email_with_attachment(
            to,
            subject=f"Системные логи Hermes ({_ts()})",
            text_body="Во вложении — выгрузка системных логов Инвестиционного процессора.",
            attachment_bytes=text.encode("utf-8"),
            filename=filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось отправить письмо: {exc}")
    audit_service.log_event(
        action="audit.logs_emailed",
        actor_type="user",
        result="ok",
        target_type="email",
        target_id=to,
        meta={"level": body.level, "lines": body.lines},
    )
    return {"success": True}


@router.get("/export")
def export_audit(
    action: Optional[str] = None,
    result: Optional[str] = None,
    actor_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_cfo),
):
    """Скачать журнал аудита в CSV (по текущим фильтрам)."""
    rows = _filtered_query(db, action, result, actor_type).order_by(AuditLog.id.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "created_at", "actor_type", "actor_id", "action",
        "target_type", "target_id", "result", "error_message",
        "ai_provider", "ai_model", "anonymized", "meta",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.created_at.isoformat() if r.created_at else "",
            r.actor_type, r.actor_id or "", r.action,
            r.target_type or "", r.target_id or "", r.result,
            (r.error_message or "").replace("\n", " "),
            r.ai_provider or "", r.ai_model or "", r.anonymized,
            "" if r.meta is None else str(r.meta),
        ])
    filename = f"hermes-audit-{_ts()}.csv"
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),  # BOM для корректной кириллицы в Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
