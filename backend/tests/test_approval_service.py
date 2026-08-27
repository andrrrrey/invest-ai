"""Тесты единой логики согласования и обработки нажатий кнопок Mattermost."""

import uuid

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.models.audit_log import AuditLog
from app.services import approval_service, mattermost_service
from app.auth import hash_password


def _mk_user(role: str) -> int:
    session = SessionLocal()
    try:
        u = User(
            email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
            full_name=f"{role.upper()} User",
            hashed_password=hash_password("x"),
            role=role,
            is_active=True,
        )
        session.add(u)
        session.commit()
        return u.id
    finally:
        session.close()


def _mk_project(owner_id: int) -> int:
    session = SessionLocal()
    try:
        p = Project(name=f"Проект {uuid.uuid4().hex[:6]}", project_type="investment",
                    status="draft", user_id=owner_id)
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _no_mattermost(monkeypatch):
    # Внешние вызовы Mattermost отключены в тестах.
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)


def test_owner_submits_then_cfo_approves(db_session):
    owner_id = _mk_user("owner")
    _mk_user("cfo")  # чтобы notify_approvers/emails нашли получателей
    cfo_id = _mk_user("cfo")
    pid = _mk_project(owner_id)

    owner = db_session.get(User, owner_id)
    cfo = db_session.get(User, cfo_id)
    project = db_session.get(Project, pid)

    approval_service.apply_status_change(db_session, project, "pending_approval", owner)
    assert project.status == "pending_approval"
    assert project.status_history[-1]["changed_by_id"] == owner_id

    approval_service.apply_status_change(db_session, project, "approved", cfo)
    assert project.status == "approved"

    # Смена статуса зафиксирована в аудите.
    row = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "status.change", AuditLog.target_id == str(pid))
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None and row.meta.get("new_status") == "approved"


def test_owner_cannot_approve(db_session):
    owner_id = _mk_user("owner")
    pid = _mk_project(owner_id)
    owner = db_session.get(User, owner_id)
    project = db_session.get(Project, pid)

    with pytest.raises(HTTPException) as exc:
        approval_service.apply_status_change(db_session, project, "approved", owner)
    assert exc.value.status_code == 403


def test_process_action_approves_via_button(db_session, monkeypatch):
    owner_id = _mk_user("owner")
    cfo_id = _mk_user("cfo")
    pid = _mk_project(owner_id)
    cfo = db_session.get(User, cfo_id)

    # Кнопку нажал CFO — сопоставляем по email из Mattermost.
    monkeypatch.setattr(mattermost_service, "get_user_email", lambda uid: cfo.email)

    context = {"decision": "approve", "project_id": pid, "token": "t"}
    result = approval_service.process_action(db_session, context, "mm-user-1")

    assert "update" in result
    assert db_session.get(Project, pid).status == "approved"


def test_rejection_dms_owner_when_bot_configured(db_session, monkeypatch):
    owner_id = _mk_user("owner")
    cfo_id = _mk_user("cfo")
    pid = _mk_project(owner_id)
    owner = db_session.get(User, owner_id)
    cfo = db_session.get(User, cfo_id)
    project = db_session.get(Project, pid)

    # Бот "настроен", перехватываем исходящие DM.
    sent = []
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: True)
    monkeypatch.setattr(mattermost_service, "post_to_email",
                        lambda to, msg, attachments=None: sent.append((to, msg)) or True)

    approval_service.apply_status_change(db_session, project, "rejected", cfo)

    # Заявителю ушёл DM о решении.
    assert any(to == owner.email and "Отклонён" in msg for to, msg in sent)
    row = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "hermes.decision_notified", AuditLog.target_id == str(pid))
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None and row.result == "ok"


def test_decision_dm_uses_mattermost_email_override(db_session, monkeypatch):
    owner_id = _mk_user("owner")
    cfo_id = _mk_user("cfo")
    pid = _mk_project(owner_id)
    owner = db_session.get(User, owner_id)
    owner.mattermost_email = "owner.mm@chat.example.com"  # отличается от основного
    db_session.commit()
    cfo = db_session.get(User, cfo_id)
    project = db_session.get(Project, pid)

    sent = []
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: True)
    monkeypatch.setattr(mattermost_service, "post_to_email",
                        lambda to, msg, attachments=None: sent.append((to, msg)) or True)

    approval_service.apply_status_change(db_session, project, "approved", cfo)

    # DM ушёл на Mattermost-email, а не на основной.
    assert any(to == "owner.mm@chat.example.com" for to, _ in sent)
    assert all(to != owner.email for to, _ in sent)


def test_process_action_unknown_user(db_session, monkeypatch):
    owner_id = _mk_user("owner")
    pid = _mk_project(owner_id)
    monkeypatch.setattr(mattermost_service, "get_user_email", lambda uid: "ghost@example.com")

    result = approval_service.process_action(
        db_session, {"decision": "approve", "project_id": pid, "token": "t"}, "mm-x"
    )
    assert "ephemeral_text" in result
    assert db_session.get(Project, pid).status == "draft"  # статус не изменился
