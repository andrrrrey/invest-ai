"""Маршруты последовательного согласования.

* ``contract`` — смарт- и лидерские контракты:
  C&B → заказчик (согласование потребности) → казначей системы Coin
  (курс и включение в резерв) → финансовый директор.
* ``order`` — проект приказа (ЛНА): C&B → юрист → CEO.

Этапы идут строго по очереди: следующий согласующий получает уведомление
(в приложении и от бота в Mattermost) только после решения «Согласовать»
предыдущего. «На доработку» закрывает текущий цикл; после исправления
маршрут запускается заново (новый цикл).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.approval_step import ApprovalStep
from ..models.project import Project
from ..models.user import User
from . import approval_roles, audit_service, change_log, links, mattermost_service
from .contract_notifications import card_url, notify_user

logger = logging.getLogger("hermes.route")

ROUTES: Dict[str, List[str]] = {
    "contract": ["cb", "customer", "treasurer", "cfo"],
    "order": ["cb", "lawyer", "ceo"],
}

ROUTE_TITLES = {
    "contract": "Согласование контракта",
    "order": "Согласование проекта приказа",
}

STEP_HINTS = {
    ("contract", "cb"): "Проверка условий вознаграждения",
    ("contract", "customer"): "Согласование потребности",
    ("contract", "treasurer"): "Согласование курса и включение в резерв",
    ("contract", "cfo"): "Финальное согласование",
    ("order", "cb"): "Проверка проекта приказа",
    ("order", "lawyer"): "Юридическая проверка",
    ("order", "ceo"): "Подписание",
}

OPEN_STATUSES = ("waiting", "active")

# Хуки завершения маршрута: (db, project, actor, comment) -> None
_ON_COMPLETE: Dict[str, Callable] = {}
_ON_REWORK: Dict[str, Callable] = {}


def register_hooks(route: str, *, on_complete: Callable = None, on_rework: Callable = None) -> None:
    if on_complete:
        _ON_COMPLETE[route] = on_complete
    if on_rework:
        _ON_REWORK[route] = on_rework


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _anchor(route: str) -> str:
    return "order" if route == "order" else "approval"


def resolve_assignee(db: Session, project: Project, role_key: str) -> Optional[User]:
    if role_key == "customer":
        scd = project.smart_contract_data or {}
        uid = scd.get("customerUserId")
        try:
            u = db.get(User, int(uid)) if uid else None
        except (TypeError, ValueError):
            u = None
        return u if u is not None and u.is_active else None
    return approval_roles.user_for(db, role_key)


def steps_of(db: Session, project_id: int, route: str, cycle: Optional[int] = None) -> List[ApprovalStep]:
    q = db.query(ApprovalStep).filter(ApprovalStep.project_id == project_id, ApprovalStep.route == route)
    if cycle is None:
        cycle = current_cycle(db, project_id, route)
    return q.filter(ApprovalStep.cycle == cycle).order_by(ApprovalStep.order_index).all()


def current_cycle(db: Session, project_id: int, route: str) -> int:
    last = (
        db.query(ApprovalStep.cycle)
        .filter(ApprovalStep.project_id == project_id, ApprovalStep.route == route)
        .order_by(ApprovalStep.cycle.desc())
        .first()
    )
    return last[0] if last else 0


def active_step(db: Session, project_id: int, route: str) -> Optional[ApprovalStep]:
    return (
        db.query(ApprovalStep)
        .filter(ApprovalStep.project_id == project_id, ApprovalStep.route == route,
                ApprovalStep.status == "active")
        .first()
    )


def cancel_open(db: Session, project_id: int, route: str) -> int:
    """Закрыть незавершённые этапы маршрута (отзыв, решение в обход маршрута)."""
    open_steps = (
        db.query(ApprovalStep)
        .filter(ApprovalStep.project_id == project_id, ApprovalStep.route == route,
                ApprovalStep.status.in_(OPEN_STATUSES))
        .all()
    )
    for s in open_steps:
        s.status = "cancelled"
    return len(open_steps)


def validate_route(db: Session, project: Project, route: str) -> Dict[str, User]:
    """Проверить, что на все роли маршрута назначены сотрудники."""
    missing, resolved = [], {}
    for role_key in ROUTES[route]:
        u = resolve_assignee(db, project, role_key)
        if u is None:
            missing.append(approval_roles.ROLE_LABELS[role_key])
        else:
            resolved[role_key] = u
    if missing:
        hint = " (выберите заказчика в контракте)" if "Заказчик" in missing else ""
        raise HTTPException(
            status_code=400,
            detail="Не назначены согласующие: " + ", ".join(missing) + hint
                   + ". Роли согласования задаются в Настройках.",
        )
    return resolved


def start_route(db: Session, project: Project, route: str, actor: User,
                *, attachment_id: Optional[int] = None) -> List[ApprovalStep]:
    """Запустить новый цикл маршрута: первый этап сразу становится активным."""
    resolved = validate_route(db, project, route)
    cancel_open(db, project.id, route)
    cycle = current_cycle(db, project.id, route) + 1
    steps = []
    for idx, role_key in enumerate(ROUTES[route]):
        step = ApprovalStep(
            project_id=project.id, route=route, cycle=cycle, order_index=idx,
            role_key=role_key, assignee_id=resolved[role_key].id,
            status="active" if idx == 0 else "waiting",
            sent_at=_now() if idx == 0 else None,
            attachment_id=attachment_id,
        )
        db.add(step)
        steps.append(step)
    db.commit()
    audit_service.log_event(
        action=f"route.{route}.started", actor_type="user", actor_id=str(actor.id),
        target_type="project", target_id=str(project.id), meta={"cycle": cycle}, db=db,
    )
    _notify_step(db, project, steps[0], actor)
    return steps


def _step_title(project: Project, step: ApprovalStep) -> str:
    label = approval_roles.ROLE_LABELS.get(step.role_key, step.role_key)
    what = "Проект приказа" if step.route == "order" else links.label_for(project)
    return f"{what} «{project.name or 'без названия'}» — ваш этап согласования ({label})"


def _notify_step(db: Session, project: Project, step: ApprovalStep, sender: Optional[User],
                 *, reminder: bool = False) -> None:
    assignee = db.get(User, step.assignee_id) if step.assignee_id else None
    if assignee is None:
        return
    hint = STEP_HINTS.get((step.route, step.role_key), "")
    total = len(ROUTES[step.route])
    lines = [f"Этап {step.order_index + 1} из {total}: {hint}."]
    if sender is not None:
        lines.append(f"Отправил(а): {sender.full_name}.")
    if step.order_index > 0:
        prev = steps_of(db, project.id, step.route, step.cycle)[step.order_index - 1]
        if prev.comment:
            lines.append(f"Комментарий предыдущего согласующего: {prev.comment}")
    if reminder:
        lines.insert(0, "Напоминание: контракт ожидает вашего решения.")
    title = ("Напоминание: " if reminder else "") + _step_title(project, step)
    message = " ".join(lines)
    attachments = None
    if mattermost_service.is_configured():
        attachments = [mattermost_service.route_step_card(
            step.id, _step_title(project, step), message, card_url(project, _anchor(step.route))
        )]
    notify_user(db, assignee, project=project, title=title, message=message,
                anchor=_anchor(step.route), mm_attachments=attachments)


def can_decide(db: Session, step: ApprovalStep, actor: User) -> bool:
    """Решение принимает назначенный согласующий; CFO — как администратор."""
    return step.status == "active" and (step.assignee_id == actor.id or actor.role == "cfo")


def decide(db: Session, step_id: int, actor: User, decision: str,
           comment: Optional[str] = None, *, nav_rate: Optional[float] = None,
           actor_type: str = "user") -> ApprovalStep:
    if decision not in ("approve", "rework"):
        raise HTTPException(status_code=400, detail="Решение: approve или rework")
    step = db.get(ApprovalStep, step_id)
    if step is None:
        raise HTTPException(status_code=404, detail="Этап согласования не найден")
    if step.status != "active":
        raise HTTPException(status_code=409, detail="Этот этап не ожидает решения — решение уже принято или очередь ещё не дошла")
    if not can_decide(db, step, actor):
        raise HTTPException(status_code=403, detail="Решение по этому этапу принимает назначенный согласующий")
    project = db.get(Project, step.project_id)
    comment = (comment or "").strip() or None

    if decision == "approve" and nav_rate is not None:
        if step.route != "contract" or step.role_key != "treasurer":
            raise HTTPException(status_code=400, detail="Курс фиксирует казначей на своём этапе")
        _apply_treasurer_rate(db, project, actor, float(nav_rate))

    step.status = "approved" if decision == "approve" else "rework"
    step.decided_at = _now()
    step.decided_by_id = actor.id
    step.comment = comment
    db.commit()
    audit_service.log_event(
        action=f"route.{step.route}.{decision}", actor_type=actor_type, actor_id=str(actor.id),
        target_type="project", target_id=str(project.id),
        meta={"step": step.role_key, "cycle": step.cycle, "has_comment": bool(comment)}, db=db,
    )

    steps = steps_of(db, project.id, step.route, step.cycle)
    if decision == "rework":
        for s in steps:
            if s.status in OPEN_STATUSES:
                s.status = "cancelled"
        db.commit()
        hook = _ON_REWORK.get(step.route)
        if hook:
            hook(db, project, actor, comment)
        return step

    nxt = next((s for s in steps if s.order_index > step.order_index and s.status == "waiting"), None)
    if nxt is not None:
        nxt.status = "active"
        nxt.sent_at = _now()
        db.commit()
        _notify_step(db, project, nxt, actor)
    else:
        hook = _ON_COMPLETE.get(step.route)
        if hook:
            hook(db, project, actor, comment)
    return step


def _apply_treasurer_rate(db: Session, project: Project, actor: User, rate: float) -> None:
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Курс должен быть больше нуля")
    from .coin_rate_service import recalc_contract_coins
    scd = dict(project.smart_contract_data or {})
    old = scd.get("navRate")
    if old is not None and abs(float(old) - rate) < 1e-9:
        return
    scd = recalc_contract_coins(scd, rate)
    scd["navRateManual"] = True
    scd["navRateSetBy"] = actor.full_name
    project.smart_contract_data = scd
    change_log.log(db, project.id, actor.id, "smart_contract_data.navRate",
                   "Курс Coin (зафиксирован казначеем)", old, rate)


def process_mm_action(db: Session, context: dict, actor: User) -> dict:
    """Нажатие кнопки в карточке этапа в Mattermost."""
    try:
        step = decide(db, int(context.get("step_id")), actor, context.get("decision"))
    except HTTPException as exc:
        return {"ephemeral_text": exc.detail}
    except (TypeError, ValueError):
        return {"ephemeral_text": "Некорректный этап."}
    project = db.get(Project, step.project_id)
    label = "согласовано" if step.status == "approved" else "возвращено на доработку"
    role = approval_roles.ROLE_LABELS.get(step.role_key, step.role_key)
    return {
        "update": {"message": f"«{project.name}» — этап «{role}»: {label} ({actor.full_name})."},
        "ephemeral_text": "Готово." + (" Комментарий можно добавить в карточке." if step.status == "rework" else ""),
    }


def _fmt_ts(value) -> Optional[str]:
    return value.isoformat() if value else None


def step_dict(db: Session, step: ApprovalStep, viewer: Optional[User] = None) -> dict:
    return {
        "id": step.id,
        "route": step.route,
        "cycle": step.cycle,
        "order_index": step.order_index,
        "role": step.role_key,
        "role_label": approval_roles.ROLE_LABELS.get(step.role_key, step.role_key),
        "hint": STEP_HINTS.get((step.route, step.role_key), ""),
        "assignee_id": step.assignee_id,
        "assignee": step.assignee.full_name if step.assignee else None,
        "status": step.status,
        "sent_at": _fmt_ts(step.sent_at),
        "decided_at": _fmt_ts(step.decided_at),
        "decided_by": step.decided_by.full_name if step.decided_by else None,
        "comment": step.comment,
        "attachment_id": step.attachment_id,
        "can_decide": bool(viewer is not None and can_decide(db, step, viewer)),
    }


def route_state(db: Session, project: Project, route: str, viewer: User) -> dict:
    cycle = current_cycle(db, project.id, route)
    steps = steps_of(db, project.id, route, cycle) if cycle else []
    active = next((s for s in steps if s.status == "active"), None)
    if not steps:
        state = "not_started"
    elif active is not None:
        state = "in_progress"
    elif any(s.status == "rework" for s in steps):
        state = "rework"
    elif all(s.status == "approved" for s in steps):
        state = "approved"
    else:
        state = "cancelled"
    preview = []
    if not steps:
        for role_key in ROUTES[route]:
            u = resolve_assignee(db, project, role_key)
            preview.append({
                "role": role_key,
                "role_label": approval_roles.ROLE_LABELS[role_key],
                "hint": STEP_HINTS.get((route, role_key), ""),
                "assignee": u.full_name if u else None,
                "status": "not_started",
            })
    return {
        "route": route,
        "title": ROUTE_TITLES[route],
        "cycle": cycle,
        "state": state,
        "steps": [step_dict(db, s, viewer) for s in steps] or preview,
        "current": step_dict(db, active, viewer) if active else None,
    }


def all_steps(db: Session, project_id: int) -> List[ApprovalStep]:
    return (
        db.query(ApprovalStep)
        .filter(ApprovalStep.project_id == project_id)
        .order_by(ApprovalStep.route, ApprovalStep.cycle, ApprovalStep.order_index)
        .all()
    )


def remind_overdue(db: Session, *, older_than_hours: int = 48) -> int:
    """Повторно напомнить согласующим о зависших этапах (раз в сутки)."""
    now = _now()
    threshold = now - dt.timedelta(hours=older_than_hours)
    day_ago = now - dt.timedelta(hours=24)
    sent = 0
    for step in db.query(ApprovalStep).filter(ApprovalStep.status == "active").all():
        sent_at = step.sent_at
        if sent_at is None:
            continue
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=dt.timezone.utc)
        reminded = step.reminded_at
        if reminded is not None and reminded.tzinfo is None:
            reminded = reminded.replace(tzinfo=dt.timezone.utc)
        if sent_at > threshold or (reminded is not None and reminded > day_ago):
            continue
        project = db.get(Project, step.project_id)
        if project is None:
            continue
        _notify_step(db, project, step, None, reminder=True)
        step.reminded_at = now
        db.commit()
        sent += 1
    return sent
