"""Журнал изменений полей контракта: кто, когда, что было и что стало."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.project_change import ProjectChange

# Поля верхнего уровня и ключи smart_contract_data, попадающие в историю.
_TOP_FIELDS = {
    "name": "Название",
    "business_unit": "Бизнес-юнит",
    "description": "Описание",
    "owner": "Ответственный",
}
_SCD_FIELDS = {
    "scType": "Тип контракта",
    "shortDescription": "Краткое описание",
    "businessEffect": "Бизнес-эффект",
    "curator": "Куратор",
    "customerName": "Заказчик",
    "deadline": "Дедлайн",
    "startDate": "Дата начала",
    "contractType": "Формат",
    "navRate": "Курс Coin",
    "fixedSalaryMonthly": "Оклад, ₽/мес",
    "variableTotal": "Переменная часть, ₽",
    "milestones": "Этапы (milestones)",
    "team": "Команда",
    "documents": "Документы",
}

_MAX = 2000


def _fmt(value: Any) -> Optional[str]:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, (dict, list)):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            # Этапы/команда — краткое представление
            parts = []
            for item in value:
                name = item.get("name") or item.get("title") or "—"
                amount = item.get("rewardRub") if "rewardRub" in item else item.get("coins")
                parts.append(f"{name}" + (f" ({amount})" if amount not in (None, "") else ""))
            text = "; ".join(parts)
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text[:_MAX]


def _norm(value: Any) -> Any:
    """Нормализация для сравнения (порядок ключей, служебные поля этапов)."""
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        skip = {"smart", "smartFeedback", "validating", "id"}
        return {k: _norm(v) for k, v in sorted(value.items()) if k not in skip}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def log(db: Session, project_id: int, user_id: Optional[int], field: str, label: str,
        old: Any, new: Any) -> None:
    db.add(ProjectChange(
        project_id=project_id, user_id=user_id, field=field, label=label,
        old_value=_fmt(old), new_value=_fmt(new),
    ))


def snapshot(project: Project) -> dict:
    snap = {f: getattr(project, f) for f in _TOP_FIELDS}
    snap["smart_contract_data"] = dict(project.smart_contract_data or {})
    return snap


def record_diff(db: Session, project: Project, before: dict, user_id: Optional[int]) -> int:
    """Записать изменения между снимком ``before`` и текущим состоянием."""
    count = 0
    for field, label in _TOP_FIELDS.items():
        old, new = before.get(field), getattr(project, field)
        if _norm(old or None) != _norm(new or None):
            log(db, project.id, user_id, field, label, old, new)
            count += 1
    old_scd = before.get("smart_contract_data") or {}
    new_scd = project.smart_contract_data or {}
    for key, label in _SCD_FIELDS.items():
        old, new = old_scd.get(key), new_scd.get(key)
        if _norm(old if old not in ("", []) else None) != _norm(new if new not in ("", []) else None):
            log(db, project.id, user_id, f"smart_contract_data.{key}", label, old, new)
            count += 1
    return count
