"""Курс Coin на дату.

Казначей (или CFO) задаёт курс с датой начала действия; при расчёте контракта
применяется курс, действующий на дату создания контракта. Пока ни одного
курса не задано, используется прежнее глобальное значение ``nav_rate``.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy.orm import Session

from .. import settings_store
from ..models.coin_rate import CoinRate
from ..models.user import User
from . import approval_roles


def _to_date(value) -> dt.date:
    if value is None:
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def record_on(db: Session, on_date=None) -> Optional[CoinRate]:
    d = _to_date(on_date)
    return (
        db.query(CoinRate)
        .filter(CoinRate.effective_date <= d)
        .order_by(CoinRate.effective_date.desc())
        .first()
    )


def rate_on(db: Session, on_date=None) -> float:
    rec = record_on(db, on_date)
    return float(rec.rate) if rec is not None else settings_store.get_nav_rate()


def current_rate(db: Session) -> float:
    return rate_on(db, dt.date.today())


def can_manage(db: Session, user: User) -> bool:
    """Курс меняют CFO (администратор) и назначенный казначей системы Coin."""
    if user.role == "cfo":
        return True
    treasurer = approval_roles.user_for(db, "treasurer")
    return treasurer is not None and treasurer.id == user.id


def recalc_contract_coins(scd: dict, rate: float) -> dict:
    """Пересчитать Coin этапов и команды смарт-контракта по новому курсу.

    Coin участников масштабируются пропорционально, чтобы распределение
    между ними сохранилось.
    """
    scd = dict(scd or {})
    if scd.get("scType") == "leadership" or not rate:
        scd["navRate"] = rate
        return scd
    old_total = sum(float(m.get("coins") or 0) for m in scd.get("milestones") or [])
    milestones = []
    for m in scd.get("milestones") or []:
        m = dict(m)
        m["coins"] = round(float(m.get("rewardRub") or 0) / rate)
        milestones.append(m)
    new_total = sum(m["coins"] for m in milestones)
    team = []
    for t in scd.get("team") or []:
        t = dict(t)
        if old_total:
            t["coins"] = round(float(t.get("coins") or 0) * new_total / old_total)
        team.append(t)
    scd.update({"milestones": milestones, "team": team, "navRate": rate,
                "totalCoins": new_total})
    return scd


def apply_creation_rate(db: Session, scd: dict, created_at=None) -> dict:
    """Зафиксировать в данных контракта курс на дату создания.

    Если казначей на своём этапе согласования скорректировал курс
    (``navRateManual``), он сохраняется.
    """
    scd = dict(scd or {})
    d = _to_date(created_at)
    scd["navRateDate"] = d.isoformat()
    if scd.get("navRateManual"):
        return scd
    rate = rate_on(db, d)
    try:
        same = abs(float(scd.get("navRate") or 0) - rate) < 1e-9
    except (TypeError, ValueError):
        same = False
    if same:
        scd["navRate"] = rate
        return scd
    return recalc_contract_coins(scd, rate)
