"""Тест фоновых напоминаний по дедлайнам майлстоунов."""

import datetime as dt
import uuid

from app.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.services import scheduler_service, mattermost_service
from app.auth import hash_password


def _mk_owner() -> tuple[int, str]:
    session = SessionLocal()
    try:
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        u = User(email=email, full_name="Owner", hashed_password=hash_password("x"),
                 role="owner", is_active=True)
        session.add(u)
        session.commit()
        return u.id, email
    finally:
        session.close()


def _mk_sc_project(owner_id: int, deadline: str, status: str = "in_progress") -> int:
    session = SessionLocal()
    try:
        p = Project(
            name=f"СК {uuid.uuid4().hex[:6]}",
            project_type="smart_contract",
            status="approved",
            user_id=owner_id,
            smart_contract_data={"milestones": [
                {"title": "Этап 1", "status": status, "deadline": deadline},
            ]},
        )
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def test_reminder_sent_for_near_deadline(monkeypatch):
    owner_id, email = _mk_owner()
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    _mk_sc_project(owner_id, tomorrow)

    sent = []
    monkeypatch.setattr(mattermost_service, "post_to_email",
                        lambda to, msg, attachments=None: sent.append((to, msg)) or True)

    count = scheduler_service.run_deadline_reminders(window_days=3)
    assert count >= 1
    assert any(to == email for to, _ in sent)


def test_no_reminder_for_far_or_done(monkeypatch):
    owner_id, email = _mk_owner()
    far = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    soon = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    _mk_sc_project(owner_id, far, status="in_progress")       # слишком далеко
    _mk_sc_project(owner_id, soon, status="paid")             # уже завершён

    sent = []
    monkeypatch.setattr(mattermost_service, "post_to_email",
                        lambda to, msg, attachments=None: sent.append((to, msg)) or True)

    scheduler_service.run_deadline_reminders(window_days=3)
    assert all(to != email for to, _ in sent)
