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


def start_scheduler() -> bool:
    """Запустить фоновый планировщик, если это включено и возможно."""
    global _scheduler
    if _scheduler is not None:
        return True
    if not settings_store.is_reminders_enabled():
        logger.info("Напоминания выключены (reminders_enabled=false) — планировщик не запущен")
        return False
    if not mattermost_service.is_configured():
        logger.warning("Mattermost не настроен — планировщик напоминаний не запущен")
        return False
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("Пакет apscheduler не установлен — планировщик недоступен")
        return False

    _scheduler = BackgroundScheduler(daemon=True)
    # Ежедневная проверка дедлайнов в 09:00.
    _scheduler.add_job(run_deadline_reminders, "cron", hour=9, minute=0, id="deadline_reminders")
    _scheduler.start()
    logger.info("Планировщик напоминаний запущен")
    return True
