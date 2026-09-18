"""Тесты удаления фактических значений (вкладка «Факт»)."""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.auth import hash_password, create_access_token

client = TestClient(app)


def _mk_user(role: str = "cfo") -> int:
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


def _new_project(headers) -> int:
    resp = client.post(
        "/api/v1/projects/",
        headers=headers,
        json={"project_type": "operational", "name": "Факт-тест"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_delete_removes_fact_value_but_keeps_plan():
    headers = _auth(_mk_user())
    pid = _new_project(headers)

    # Запишем план и факт.
    resp = client.put(
        f"/api/v1/projects/{pid}/fact",
        headers=headers,
        json=[{"year": 2026, "month": 3, "metric_name": "New Logo", "plan_value": 5, "fact_value": 2}],
    )
    assert resp.status_code == 200, resp.text

    # Удалим факт — план должен остаться, строка сохраниться.
    resp = client.post(
        f"/api/v1/projects/{pid}/fact/delete",
        headers=headers,
        json=[{"year": 2026, "month": 3, "metric_name": "New Logo"}],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 1

    rows = client.get(f"/api/v1/projects/{pid}/fact", headers=headers).json()
    row = next(r for r in rows if r["metric_name"] == "New Logo")
    assert row["fact_value"] is None
    assert row["plan_value"] == 5


def test_delete_drops_row_when_no_plan():
    headers = _auth(_mk_user())
    pid = _new_project(headers)

    client.put(
        f"/api/v1/projects/{pid}/fact",
        headers=headers,
        json=[{"year": 2026, "month": 4, "metric_name": "MRR", "fact_value": 100}],
    )
    resp = client.post(
        f"/api/v1/projects/{pid}/fact/delete",
        headers=headers,
        json=[{"year": 2026, "month": 4, "metric_name": "MRR"}],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 1

    rows = client.get(f"/api/v1/projects/{pid}/fact", headers=headers).json()
    assert not any(r["metric_name"] == "MRR" for r in rows)


def test_delete_unknown_cell_is_noop():
    headers = _auth(_mk_user())
    pid = _new_project(headers)
    resp = client.post(
        f"/api/v1/projects/{pid}/fact/delete",
        headers=headers,
        json=[{"year": 2030, "month": 1, "metric_name": "Нет такой"}],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 0
