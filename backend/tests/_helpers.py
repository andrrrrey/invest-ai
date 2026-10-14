"""Общие хелперы для тестов модуля контрактов."""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.auth import hash_password, create_access_token

client = TestClient(app)


def mk_user(role: str = "owner", full_name: str | None = None) -> int:
    session = SessionLocal()
    try:
        u = User(
            email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
            full_name=full_name or f"{role.upper()} {uuid.uuid4().hex[:4]}",
            hashed_password=hash_password("x"),
            role=role,
            is_active=True,
        )
        session.add(u)
        session.commit()
        return u.id
    finally:
        session.close()


def auth(uid: int) -> dict:
    session = SessionLocal()
    try:
        u = session.get(User, uid)
        token = create_access_token({"sub": u.email, "role": u.role, "user_id": u.id})
        return {"Authorization": f"Bearer {token}"}
    finally:
        session.close()


def mk_contract(owner_id: int, sc_type: str = "smart", status: str = "draft", **scd) -> int:
    session = SessionLocal()
    try:
        data = {"scType": sc_type, "milestones": [], "team": []}
        data.update(scd)
        p = Project(
            project_type="smart_contract",
            name=f"Контракт {uuid.uuid4().hex[:6]}",
            user_id=owner_id,
            owner="Владелец",
            status=status,
            smart_contract_data=data,
        )
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def get_project(pid: int) -> Project:
    session = SessionLocal()
    try:
        p = session.get(Project, pid)
        session.expunge(p)
        return p
    finally:
        session.close()


def setup_route_roles() -> dict:
    """Назначить согласующих на все роли маршрутов; вернуть их id."""
    from app import settings_store
    ids = {
        "cb": mk_user("manager", full_name="Кулеева Маргарита"),
        "treasurer": mk_user("owner", full_name="Кувшинчикова Кристина"),
        "cfo": mk_user("cfo", full_name="Хагуш Лонда"),
        "lawyer": mk_user("owner", full_name="Юристов Юрий"),
        "ceo": mk_user("ceo", full_name="Генеральный Директор"),
    }
    settings_store.set_approval_roles(ids)
    return ids
