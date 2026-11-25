"""
API справочника МВЗ (круги → подкруги).

Чтение доступно любому авторизованному пользователю — справочник нужен
для выпадающих списков в визарде заявки. Изменение — только CFO
(раздел «Настройки → Справочник МВЗ»).
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ... import settings_store
from ...auth import get_current_user, require_cfo
from ...services.mvz_reference import DEFAULT_MVZ, validate_mvz

router = APIRouter(prefix="/mvz", tags=["mvz"])


class MvzReferenceUpdate(BaseModel):
    main_circles: list = []
    sub1: dict = {}
    sub2: dict = {}


@router.get("/reference")
def get_mvz_reference(_=Depends(get_current_user)) -> dict:
    """Текущий справочник МВЗ. Доступен всем авторизованным пользователям."""
    return settings_store.get_mvz_reference()


@router.get("/default")
def get_default_mvz_reference(_=Depends(require_cfo)) -> dict:
    """Эталонный справочник МВЗ (для кнопки «Вернуть к эталону»). CFO only."""
    return DEFAULT_MVZ


@router.post("/reference")
def update_mvz_reference(body: MvzReferenceUpdate, _=Depends(require_cfo)) -> dict:
    """Сохранить справочник МВЗ. CFO only."""
    try:
        normalized = validate_mvz(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    settings_store.set_mvz_reference(normalized)
    return {"success": True, "mvz_reference": normalized}
