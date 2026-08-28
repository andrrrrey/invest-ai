"""
Фоновые напоминания по дедлайнам майлстоунов.

Периодически проверяет смарт-контракты с приближающимися дедлайнами
незавершённых майлстоунов и шлёт заявителю напоминание в Mattermost обновить
факт и статус. Планировщик (APScheduler) запускается только если напоминания
включены в настройках и бот Mattermost настроен; пакет импортируется лениво,
поэтому его отсутствие не ломает приложение.

Немедленное напоминание при отправке на согласование — событийное и живёт в
``approval_service`` (не здесь).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from ..database import SessionLocal
from ..models.project import Project
from ..models.user import User
from .. import settings_store
from . import mattermost_service, audit_service

logger = logging.getLogger("hermes.scheduler")

_scheduler = None
# Статусы майлстоунов, которые считаются завершёнными (напоминать не нужно).
_DONE_MILESTONE_STATUSES = {"paid", "done", "completed"}


def _parse_deadline(value) -> Optional[dt.date]:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def run_deadline_reminders(window_days: int = 3) -> int:
    """Разослать напоминания по майлстоунам с дедлайном в ближайшие
    ``window_days`` дней. Возвращает число отправленных напоминаний."""
    today = dt.date.today()
    horizon = today + dt.timedelta(days=window_days)
    sent = 0
    db = SessionLocal()
    try:
        projects = (
            db.query(Project)
            .filter(Project.project_type == "smart_contract")
            .all()
        )
        for p in projects:
            scd = p.smart_contract_data or {}
            due = []
            for m in scd.get("milestones") or []:
                if not isinstance(m, dict):
                    continue
                if (m.get("status") or "").lower() in _DONE_MILESTONE_STATUSES:
                    continue
                deadline = _parse_deadline(m.get("deadline"))
                if deadline and today <= deadline <= horizon:
                    due.append((m.get("title") or m.get("name") or "майлстоун", deadline))
            if not due:
                continue
            owner = db.get(User, p.user_id) if p.user_id else None
            owner_email = mattermost_service.mattermost_email(owner)
            if not owner_email:
                continue
            lines = "\n".join(f"• {title} — до {d.isoformat()}" for title, d in due)
            ok = mattermost_service.post_to_email(
                owner_email,
                f"Напоминание по проекту «{p.name or '(без названия)'}»: "
                f"приближаются дедлайны майлстоунов. Обновите факт и статус:\n{lines}",
            )
            if ok:
                sent += 1
                audit_service.log_event(
                    action="hermes.deadline_reminder",
                    actor_type="hermes",
                    result="ok",
                    target_type="project",
                    target_id=str(p.id),
                    meta={"milestones_due": len(due)},
                )
        return sent
    finally:
        db.close()


def _digest_recipient_emails(db) -> list:
    """Email'ы руководства (CFO/CEO/менеджеры) для дайджеста."""
    users = (
        db.query(User)
        .filter(User.role.in_(["cfo", "ceo", "manager"]), User.is_active == True)  # noqa: E712
        .all()
    )
    return [e for e in (mattermost_service.mattermost_email(u) for u in users) if e]


def build_weekly_digest(db) -> str:
    """Собрать текст еженедельного дайджеста по портфелю (Markdown для Mattermost)."""
    from ..mcp import tools
    from . import links

    stats = tools.budget_status(db)
    by_status = stats.get("by_status") or {}
    deadlines = tools.list_upcoming_deadlines(db, window_days=7)
    risks = tools.risk_overview(db)
    overdue_fact = tools.list_overdue_fact(db, window_months=2)

    lines = ["**Еженедельный дайджест по портфелю**", ""]
    lines.append(
        f"Проектов: {stats.get('total_projects', 0)} · "
        f"на согласовании: {by_status.get('pending_approval', 0)} · "
        f"утверждено: {by_status.get('approved', 0)}"
    )
    budget = stats.get("investment_budget")
    if budget is not None:
        lines.append(
            f"Бюджет: одобрено {stats.get('approved_investment', 0):,.0f} из "
            f"{budget:,.0f} ₽ (доступно {stats.get('available_for_investment', 0):,.0f} ₽)"
        )

    dl = deadlines.get("deadlines") or []
    if dl:
        lines.append("")
        lines.append(f"**Дедлайны (7 дней), просрочено {deadlines.get('overdue_count', 0)}:**")
        for d in dl[:8]:
            mark = "⚠️ просрочен" if d.get("overdue") else f"через {d.get('days_left')} дн."
            lines.append(f"• {d.get('project')} — {d.get('milestone')} ({mark})")

    if risks.get("count"):
        lines.append("")
        lines.append(f"**Высокий риск ({risks['count']}):**")
        for r in (risks.get("projects") or [])[:8]:
            link = r.get("url")
            name = f"[{r.get('name')}]({link})" if link else r.get("name")
            lines.append(f"• {name}")

    if overdue_fact.get("count"):
        lines.append("")
        lines.append(f"**Давно не обновляли факт ({overdue_fact['count']}):**")
        for p in (overdue_fact.get("projects") or [])[:8]:
            link = p.get("url")
            name = f"[{p.get('name')}]({link})" if link else p.get("name")
            lines.append(f"• {name} (последний факт: {p.get('last_fact') or 'нет'})")

    base = links.app_base_url()
    if base:
        lines.append("")
        lines.append(f"[Открыть портфель]({base}/project-list)")
    return "\n".join(lines)


def run_weekly_digest() -> int:
    """Разослать еженедельный дайджест руководству. Возвращает число отправок."""
    if not mattermost_service.is_configured():
        return 0
    db = SessionLocal()
    try:
        text = build_weekly_digest(db)
        emails = _digest_recipient_emails(db)
    finally:
        db.close()
    sent = 0
    for email in emails:
        if mattermost_service.post_to_email(email, text):
            sent += 1
    audit_service.log_event(
        action="hermes.weekly_digest",
        actor_type="hermes",
        result="ok",
        meta={"recipients": sent},
    )
    return sent


def start_scheduler() -> bool:
    """Запустить фоновый планировщик, если это включено и возможно."""
    global _scheduler
    if _scheduler is not None:
        return True
    reminders_on = settings_store.is_reminders_enabled()
    digest_on = settings_store.is_digest_enabled()
    if not (reminders_on or digest_on):
        logger.info("Напоминания и дайджест выключены — планировщик не запущен")
        return False
    if not mattermost_service.is_configured():
        logger.warning("Mattermost не настроен — планировщик не запущен")
        return False
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("Пакет apscheduler не установлен — планировщик недоступен")
        return False

    _scheduler = BackgroundScheduler(daemon=True)
    if reminders_on:
        # Ежедневная проверка дедлайнов в 09:00.
        _scheduler.add_job(run_deadline_reminders, "cron", hour=9, minute=0, id="deadline_reminders")
    if digest_on:
        # Еженедельный дайджест: понедельник, 09:00.
        _scheduler.add_job(run_weekly_digest, "cron", day_of_week="mon", hour=9, minute=0, id="weekly_digest")
    _scheduler.start()
    logger.info("Планировщик запущен (reminders=%s, digest=%s)", reminders_on, digest_on)
    return True
