"""Тесты возможностей CFO: завести заявку за сотрудника и сменить ответственного."""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.auth import hash_password, create_access_token

client = TestClient(app)


def _mk_user(role: str) -> int:
    session = SessionLocal()
    try:
        u = User(
            email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
            full_name=f"{role.upper()} {uuid.uuid4().hex[:4]}",
            hashed_password=hash_password("x"),
            role=role,
            is_active=True,
        )
        session.add(u)
        session.commit()
        return u.id
    finally:
        session.close()


def _auth(uid: int) -> dict:
    session = SessionLocal()
    try:
        u = session.get(User, uid)
        token = create_access_token({"sub": u.email, "role": u.role, "user_id": u.id})
        return {"Authorization": f"Bearer {token}"}
    finally:
        session.close()


def test_cfo_creates_on_behalf_of_employee():
    cfo_id = _mk_user("cfo")
    owner_id = _mk_user("owner")

    resp = client.post(
        "/api/v1/projects/",
        headers=_auth(cfo_id),
        json={"project_type": "investment", "name": "За сотрудника", "owner_user_id": owner_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["user_id"] == owner_id

    session = SessionLocal()
    try:
        target = session.get(User, owner_id)
        assert data["owner"] == target.full_name
    finally:
        session.close()


def test_non_cfo_cannot_create_on_behalf():
    manager_id = _mk_user("manager")
    owner_id = _mk_user("owner")

    resp = client.post(
        "/api/v1/projects/",
        headers=_auth(manager_id),
        json={"project_type": "investment", "name": "Попытка", "owner_user_id": owner_id},
    )
    assert resp.status_code == 201, resp.text
    # owner_user_id игнорируется для не-CFO — владельцем остаётся создатель.
    assert resp.json()["user_id"] == manager_id


def test_cfo_reassigns_responsible():
    cfo_id = _mk_user("cfo")
    owner1 = _mk_user("owner")
    owner2 = _mk_user("owner")

    session = SessionLocal()
    try:
        p = Project(name="Проект", project_type="investment", status="draft", user_id=owner1)
        session.add(p)
        session.commit()
        pid = p.id
        owner2_name = session.get(User, owner2).full_name
    finally:
        session.close()

    resp = client.patch(
        f"/api/v1/projects/{pid}/reassign",
        headers=_auth(cfo_id),
        json={"user_id": owner2},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == owner2
    assert data["owner"] == owner2_name


def test_manager_cannot_reassign():
    manager_id = _mk_user("manager")
    owner1 = _mk_user("owner")
    owner2 = _mk_user("owner")

    session = SessionLocal()
    try:
        p = Project(name="Проект2", project_type="investment", status="draft", user_id=owner1)
        session.add(p)
        session.commit()
        pid = p.id
    finally:
        session.close()

    resp = client.patch(
        f"/api/v1/projects/{pid}/reassign",
        headers=_auth(manager_id),
        json={"user_id": owner2},
    )
    assert resp.status_code == 403


def test_reject_with_comment_persists_reason():
    cfo_id = _mk_user("cfo")
    owner_id = _mk_user("owner")

    session = SessionLocal()
    try:
        p = Project(name="Отклоняемый", project_type="investment", status="pending_approval", user_id=owner_id)
        session.add(p)
        session.commit()
        pid = p.id
    finally:
        session.close()

    resp = client.patch(
        f"/api/v1/projects/{pid}/status",
        headers=_auth(cfo_id),
        json={"status": "rejected", "comment": "Не проходит по бюджету"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["rejection_reason"] == "Не проходит по бюджету"
