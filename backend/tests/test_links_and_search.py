"""Тесты ссылок на проекты, поиска по названию и ссылки в карточке согласования."""

import uuid

from app.database import SessionLocal
from app.models.project import Project
from app.mcp import registry
from app.services import links, mattermost_service
from app import settings_store


def _seed(name: str, ptype: str = "investment") -> int:
    session = SessionLocal()
    try:
        p = Project(name=name, project_type=ptype, status="approved")
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def test_project_url_by_type(monkeypatch):
    monkeypatch.setattr(settings_store, "get_app_base_url", lambda: "https://invest.futuguru.com")
    assert links.project_url("investment", 5) == "https://invest.futuguru.com/project?id=5"
    assert links.project_url("operational", 7) == "https://invest.futuguru.com/op-project?id=7"
    assert links.project_url("smart_contract", 9) == "https://invest.futuguru.com/smart-contract?id=9"


def test_project_url_none_without_base(monkeypatch):
    monkeypatch.setattr(settings_store, "get_app_base_url", lambda: None)
    assert links.project_url("investment", 5) is None


def test_find_projects_by_name(monkeypatch):
    monkeypatch.setattr(settings_store, "get_app_base_url", lambda: "https://invest.futuguru.com")
    unique = f"Дельта-{uuid.uuid4().hex[:6]}"
    pid = _seed(unique, "operational")

    res = registry.call_tool("find_projects", {"query": unique[:8].lower()})
    match = [p for p in res["projects"] if p["id"] == pid]
    assert match, "проект должен находиться по части названия"
    assert match[0]["url"] == f"https://invest.futuguru.com/op-project?id={pid}"


def test_find_projects_empty_query():
    res = registry.call_tool("find_projects", {"query": "   "})
    assert res["count"] == 0


def test_approval_card_has_project_link(monkeypatch):
    monkeypatch.setattr(settings_store, "get_app_base_url", lambda: "https://invest.futuguru.com")
    monkeypatch.setattr(settings_store, "get_mattermost_integration_url", lambda: "https://invest.futuguru.com")
    monkeypatch.setattr(settings_store, "get_mattermost_command_token", lambda: "tok")

    card = mattermost_service._approval_card(42, "Тест", "Иван", project_type="investment")
    assert card["title_link"] == "https://invest.futuguru.com/project?id=42"
    assert "/project?id=42" in card["text"]
