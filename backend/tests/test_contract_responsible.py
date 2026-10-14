"""Пункт 3 КП: выбор ответственного при создании контракта."""

from _helpers import client, mk_user, auth, get_project
from app.database import SessionLocal
from app.models.notification import Notification


def _create(author, **over):
    body = {"project_type": "smart_contract", "name": "За коллегу", "status": "draft",
            "smart_contract_data": {"scType": "leadership"}}
    body.update(over)
    return client.post("/api/v1/projects/", headers=auth(author), json=body)


def test_owner_creates_contract_for_colleague_and_keeps_access():
    author = mk_user("owner")
    leader = mk_user("owner")
    r = _create(author, owner_user_id=leader)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["user_id"] == leader
    assert data["created_by_id"] == author

    # Автор по-прежнему видит и редактирует контракт, хоть и не ответственный.
    assert client.get(f"/api/v1/projects/{data['id']}", headers=auth(author)).status_code == 200
    ids = [p["id"] for p in client.get("/api/v1/projects/?project_type=smart_contract", headers=auth(author)).json()]
    assert data["id"] in ids
    assert client.patch(f"/api/v1/projects/{data['id']}/status", headers=auth(author),
                        json={"status": "pending_approval"}).status_code == 200

    # Назначенный получил уведомление со ссылкой на карточку контракта.
    s = SessionLocal()
    try:
        n = s.query(Notification).filter_by(user_id=leader, project_id=data["id"]).first()
        assert n is not None and n.link.startswith("/smart-contract?id=")
    finally:
        s.close()


def test_owner_cannot_assign_investment_project():
    author = mk_user("owner")
    other = mk_user("owner")
    r = client.post("/api/v1/projects/", headers=auth(author),
                    json={"project_type": "investment", "name": "X", "owner_user_id": other})
    assert r.json()["user_id"] == author


def test_change_responsible_in_draft_via_put():
    author = mk_user("manager")
    leader = mk_user("owner")
    pid = _create(author).json()["id"]
    r = client.put(f"/api/v1/projects/{pid}", headers=auth(author),
                   json={"project_type": "smart_contract", "owner_user_id": leader})
    assert r.status_code == 200, r.text
    assert get_project(pid).user_id == leader


def test_inactive_responsible_rejected():
    author = mk_user("owner")
    r = _create(author, owner_user_id=999999)
    assert r.status_code == 400
