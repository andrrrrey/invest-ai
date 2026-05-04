import os
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.attachment import Attachment
from ...models.project import Project
from ...auth import get_current_user, require_approver

router = APIRouter(tags=["attachments"])

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/plain",
    "application/octet-stream",  # some browsers send this for .docx
}


def _ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


class AttachmentRead(BaseModel):
    id: int
    original_name: str
    file_size: int
    uploaded_at: datetime
    uploader_name: str

    class Config:
        from_attributes = True


@router.post("/projects/{project_id}/attachments", response_model=AttachmentRead, status_code=201)
async def upload_attachment(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")

    ext = _ext(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат файла. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл превышает допустимый размер 25 МБ")

    project_dir = os.path.join(ATTACHMENTS_DIR, str(project_id))
    os.makedirs(project_dir, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(project_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(content)

    att = Attachment(
        project_id=project_id,
        uploaded_by_id=current_user.id,
        filename=stored_name,
        original_name=file.filename or stored_name,
        file_size=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    return AttachmentRead(
        id=att.id,
        original_name=att.original_name,
        file_size=att.file_size,
        uploaded_at=att.uploaded_at,
        uploader_name=current_user.full_name,
    )


@router.get("/projects/{project_id}/attachments", response_model=List[AttachmentRead])
def list_attachments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Проект не найден")
    rows = (
        db.query(Attachment)
        .filter(Attachment.project_id == project_id)
        .order_by(Attachment.uploaded_at.desc())
        .all()
    )
    return [
        AttachmentRead(
            id=a.id,
            original_name=a.original_name,
            file_size=a.file_size,
            uploaded_at=a.uploaded_at,
            uploader_name=a.uploader.full_name if a.uploader else "—",
        )
        for a in rows
    ]


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    att = db.get(Attachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = os.path.join(ATTACHMENTS_DIR, str(att.project_id), att.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    return FileResponse(
        path=file_path,
        filename=att.original_name,
        media_type="application/octet-stream",
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_approver),
):
    att = db.get(Attachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = os.path.join(ATTACHMENTS_DIR, str(att.project_id), att.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    db.delete(att)
    db.commit()
