"""Тесты новых MCP-инструментов агента Hermes и еженедельного дайджеста."""

import uuid

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.models.tranche import Tranche
from app.models.comment import Comment
from app.models.fact_entry import FactEntry
from app.mcp import registry, tools
from app.services import scheduler_service
from app import settings_store
from app.auth import hash_password


def _seed_project(**kw) -> int:
    session = SessionLocal()
    try:
        p = Project(name=kw.get("name", f"Проект {uuid.uuid4().hex[:6]}"),
                    project_type=kw.get("project_type", "investment"),
                    status=kw.get("status", "approved"),
                    business_unit=kw.get("business_unit"),
                    owner=kw.get("owner"),
                    metrics=kw.get("metrics"),
                    risks_data=kw.get("risks_data"),
                    user_id=kw.get("user_id"))
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def test_get_tranches_totals():
    pid = _seed_project()
    session = SessionLocal()
    try:
        session.add_all([
            Tranche(project_id=pid, amount=100.0, status="approved", order_index=0),
            Tranche(project_id=pid, amount=50.0, status="paid", order_index=1),
            Tranche(project_id=pid, amount=30.0, status="requested", order_index=2),
        ])
        session.commit()
    finally:
        session.close()
    res = registry.call_tool("get_tranches", {"project_id": pid})
    assert res["count"] == 3
    assert res["total_amount"] == 180.0
    assert res["approved_amount"] == 100.0
    assert res["paid_amount"] == 50.0


def test_get_comments():
    pid = _seed_project()
    session = SessionLocal()
    try:
        u = User(email=f"c-{uuid.uuid4().hex[:6]}@e.com", full_name="Автор",
                 hashed_password=hash_password("x"), role="owner", is_active=True)
        session.add(u); session.commit()
        session.add(Comment(project_id=pid, user_id=u.id, text="Первый"))
        session.commit()
    finally:
        session.close()
    res = registry.call_tool("get_comments", {"project_id": pid})
    assert res["count"] == 1
    assert res["comments"][0]["text"] == "Первый"
    assert res["comments"][0]["author"] == "Автор"


def test_compare_projects():
    a = _seed_project(metrics={"npv": 100, "irr": 10})
    b = _seed_project(metrics={"npv": 200, "irr": 20})
    res = registry.call_tool("compare_projects", {"project_ids": [a, b]})
    assert res["count"] == 2
    ids = {p["id"] for p in res["projects"]}
    assert {a, b} == ids


def test_portfolio_by_dimension():
    _seed_project(business_unit="WealthTech", metrics={"npv": 100})
    res = registry.call_tool("portfolio_by_dimension", {"dimension": "business_unit"})
    assert res["dimension"] == "business_unit"
    assert any(g["key"] == "WealthTech" for g in res["groups"])


def test_budget_status_shape():
    res = registry.call_tool("budget_status")
    assert "investment_budget" in res and "by_status" in res


def test_list_overdue_fact_flags_no_fact():
    pid = _seed_project(status="approved")
    res = registry.call_tool("list_overdue_fact", {"window_months": 2})
    assert any(p["id"] == pid and p["last_fact"] is None for p in res["projects"])


def test_risk_overview():
    pid = _seed_project(risks_data={"overall_risk": "высокий"})
    res = registry.call_tool("risk_overview")
    assert any(p["id"] == pid for p in res["projects"])


def test_find_projects_by_owner():
    owner = f"Ерофеев-{uuid.uuid4().hex[:5]}"
    pid = _seed_project(owner=owner)
    res = registry.call_tool("find_projects", {"query": owner[:8].lower()})
    assert any(p["id"] == pid for p in res["projects"])


def test_add_comment_gated_off_by_default():
    pid = _seed_project()
    res = registry.call_tool("add_comment", {"project_id": pid, "text": "привет"})
    assert "error" in res  # режим записи выключен


def test_add_comment_writes_when_enabled(monkeypatch):
    pid = _seed_project()
    monkeypatch.setattr(settings_store, "is_hermes_write_enabled", lambda: True)
    res = registry.call_tool("add_comment", {"project_id": pid, "text": "заметка"})
    assert res.get("ok") is True
    session = SessionLocal()
    try:
        c = session.query(Comment).filter(Comment.project_id == pid).first()
        assert c is not None and "via Hermes" in c.text
    finally:
        session.close()


def test_weekly_digest_builds(monkeypatch):
    monkeypatch.setattr(settings_store, "get_app_base_url", lambda: "https://invest.futuguru.com")
    _seed_project(status="pending_approval")
    session = SessionLocal()
    try:
        text = scheduler_service.build_weekly_digest(session)
    finally:
        session.close()
    assert "дайджест" in text.lower()
    assert "invest.futuguru.com/project-list" in text
