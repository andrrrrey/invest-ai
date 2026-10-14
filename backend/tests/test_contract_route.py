"""Пункт 7 КП: маршрут согласования контракта и история."""

import datetime as dt

from _helpers import client, mk_user, auth, get_project, setup_route_roles
from app.database import SessionLocal
from app.models.approval_step import ApprovalStep
from app.models.notification import Notification
from app.services import mattermost_service, route_service


def _contract(author, customer, **scd):
    data = {"scType": "smart", "customerUserId": customer, "navRate": 10.0,
            "milestones": [{"name": "Этап", "rewardRub": 1000, "coins": 100}],
            "team": [{"name": "А", "coins": 100}]}
    data.update(scd)
    r = client.post("/api/v1/projects/", headers=auth(author), json={
        "project_type": "smart_contract", "name": "Маршрут", "status": "draft",
        "smart_contract_data": data})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _submit(author, pid):
    return client.patch(f"/api/v1/projects/{pid}/status", headers=auth(author), json={"status": "pending_approval"})


def _route(uid, pid, route="contract"):
    return client.get(f"/api/v1/projects/{pid}/route?route={route}", headers=auth(uid)).json()


def _decide(uid, pid, step_id, decision="approve", **extra):
    return client.post(f"/api/v1/projects/{pid}/route/steps/{step_id}/decision",
                       headers=auth(uid), json={"decision": decision, **extra})


def test_sequential_route_to_approval(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    roles = setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager", full_name="Заказчиков Иван")
    pid = _contract(author, customer)
    assert _submit(author, pid).status_code == 200

    state = _route(author, pid)
    assert state["state"] == "in_progress"
    assert [s["role"] for s in state["steps"]] == ["cb", "customer", "treasurer", "cfo"]
    assert [s["status"] for s in state["steps"]] == ["active", "waiting", "waiting", "waiting"]
    assert state["steps"][1]["assignee"] == "Заказчиков Иван"
    steps = {s["role"]: s["id"] for s in state["steps"]}

    # Следующий согласующий не может решить, пока очередь не дошла.
    assert _decide(customer, pid, steps["customer"]).status_code == 409
    # Посторонний не может решать за C&B.
    assert _decide(customer, pid, steps["cb"]).status_code == 403

    assert _decide(roles["cb"], pid, steps["cb"], comment="ок").status_code == 200
    # Уведомление заказчику пришло только сейчас.
    s = SessionLocal()
    try:
        assert s.query(Notification).filter_by(user_id=customer, project_id=pid).count() == 1
    finally:
        s.close()
    assert _decide(customer, pid, steps["customer"]).status_code == 200
    # Казначей фиксирует курс — Coin пересчитываются.
    assert _decide(roles["treasurer"], pid, steps["treasurer"], nav_rate=25.0).status_code == 200
    scd = get_project(pid).smart_contract_data
    assert scd["navRate"] == 25.0 and scd["navRateManual"] is True
    assert scd["milestones"][0]["coins"] == 40
    assert get_project(pid).status == "pending_approval"

    r = _decide(roles["cfo"], pid, steps["cfo"])
    assert r.status_code == 200 and r.json()["state"] == "approved"
    assert get_project(pid).status == "approved"

    history = client.get(f"/api/v1/projects/{pid}/history", headers=auth(author)).json()
    kinds = {e["kind"] for e in history}
    assert {"route_sent", "route_approved", "status", "change"} <= kinds


def test_rework_closes_cycle_and_resubmit_starts_new(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    roles = setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager")
    pid = _contract(author, customer)
    _submit(author, pid)
    steps = {s["role"]: s["id"] for s in _route(author, pid)["steps"]}
    _decide(roles["cb"], pid, steps["cb"])
    # Возврат без комментария не принимается.
    assert _decide(customer, pid, steps["customer"], decision="rework").status_code == 400
    assert _decide(customer, pid, steps["customer"], decision="rework", comment="Уточнить KPI").status_code == 200
    p = get_project(pid)
    assert p.status == "rework_needed"
    assert p.status_history[-1]["comment"] == "Уточнить KPI"
    state = _route(author, pid)
    assert state["state"] == "rework"
    assert [s["status"] for s in state["steps"]] == ["approved", "rework", "cancelled", "cancelled"]

    # Автор исправляет и отправляет снова — новый цикл с начала маршрута.
    assert client.put(f"/api/v1/projects/{pid}", headers=auth(author),
                      json={"project_type": "smart_contract", "name": "Маршрут v2"}).status_code == 200
    assert _submit(author, pid).status_code == 200
    state = _route(author, pid)
    assert state["cycle"] == 2 and state["steps"][0]["status"] == "active"


def test_submit_requires_assigned_approvers(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    setup_route_roles()
    author = mk_user("owner")
    pid = _contract(author, None)
    r = _submit(author, pid)
    assert r.status_code == 400 and "Заказчик" in r.json()["detail"]
    assert get_project(pid).status == "draft"


def test_manager_cannot_bypass_route_but_cfo_can(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager")
    pid = _contract(author, customer)
    _submit(author, pid)
    manager = mk_user("manager")
    r = client.patch(f"/api/v1/projects/{pid}/status", headers=auth(manager), json={"status": "approved"})
    assert r.status_code == 403
    cfo = mk_user("cfo")
    r = client.patch(f"/api/v1/projects/{pid}/status", headers=auth(cfo), json={"status": "rejected", "comment": "нет бюджета"})
    assert r.status_code == 200
    assert _route(author, pid)["state"] == "cancelled"


def test_mattermost_button_decides_step(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    roles = setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager")
    pid = _contract(author, customer)
    _submit(author, pid)
    step_id = _route(author, pid)["steps"][0]["id"]

    s = SessionLocal()
    try:
        from app.models.user import User
        cb_email = s.get(User, roles["cb"]).email
    finally:
        s.close()
    monkeypatch.setattr(mattermost_service, "get_user_email", lambda mm_id: cb_email.upper())
    from app.services import approval_service
    s = SessionLocal()
    try:
        res = approval_service.process_action(
            s, {"kind": "route_step", "step_id": step_id, "decision": "approve"}, "mm-user")
    finally:
        s.close()
    assert "согласовано" in res["update"]["message"]
    assert _route(author, pid)["steps"][1]["status"] == "active"


def test_overdue_reminder(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager")
    pid = _contract(author, customer)
    _submit(author, pid)
    s = SessionLocal()
    try:
        step = s.query(ApprovalStep).filter_by(project_id=pid, status="active").first()
        step.sent_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
        s.commit()
        assert route_service.remind_overdue(s) >= 1
        # Повторно в тот же день не напоминаем.
        before = route_service.remind_overdue(s)
        s.refresh(step)
        assert step.reminded_at is not None
    finally:
        s.close()
