"""Курс Coin на дату: история, курс на дату, установка (CFO / казначей)."""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models.coin_rate import CoinRate
from ...models.user import User
from ...services import audit_service, coin_rate_service

router = APIRouter(prefix="/coin-rates", tags=["coin-rates"])


class CoinRateIn(BaseModel):
    effective_date: dt.date
    rate: float = Field(gt=0)
    comment: Optional[str] = None


def _out(r: CoinRate) -> dict:
    return {
        "id": r.id,
        "effective_date": r.effective_date.isoformat(),
        "rate": r.rate,
        "comment": r.comment,
        "created_by": r.created_by.full_name if r.created_by else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("")
def list_rates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rates = db.query(CoinRate).order_by(CoinRate.effective_date.desc()).all()
    return {
        "items": [_out(r) for r in rates],
        "current_rate": coin_rate_service.current_rate(db),
        "can_manage": coin_rate_service.can_manage(db, current_user),
    }


@router.get("/effective")
def effective_rate(
    date: Optional[dt.date] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    d = date or dt.date.today()
    rec = coin_rate_service.record_on(db, d)
    return {
        "date": d.isoformat(),
        "rate": coin_rate_service.rate_on(db, d),
        "effective_date": rec.effective_date.isoformat() if rec else None,
    }


def _require_manager(db: Session, user: User) -> None:
    if not coin_rate_service.can_manage(db, user):
        raise HTTPException(status_code=403, detail="Курс Coin устанавливают CFO и казначей системы Coin")


@router.post("", status_code=201)
def set_rate(body: CoinRateIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Установить курс с даты. Повторная установка на ту же дату заменяет курс."""
    _require_manager(db, current_user)
    rec = db.query(CoinRate).filter(CoinRate.effective_date == body.effective_date).first()
    old = rec.rate if rec else None
    if rec is None:
        rec = CoinRate(effective_date=body.effective_date)
        db.add(rec)
    rec.rate = body.rate
    rec.comment = body.comment
    rec.created_by_id = current_user.id
    db.commit()
    db.refresh(rec)
    audit_service.log_event(
        action="coin_rate.set", actor_type="user", actor_id=str(current_user.id),
        target_type="coin_rate", target_id=rec.effective_date.isoformat(),
        meta={"rate": body.rate, "old_rate": old}, db=db,
    )
    return _out(rec)


@router.delete("/{rate_id}", status_code=204)
def delete_rate(rate_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_manager(db, current_user)
    rec = db.get(CoinRate, rate_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    audit_service.log_event(
        action="coin_rate.delete", actor_type="user", actor_id=str(current_user.id),
        target_type="coin_rate", target_id=rec.effective_date.isoformat(),
        meta={"rate": rec.rate}, db=db,
    )
    db.delete(rec)
    db.commit()
