"""Тесты MCP-инструментов и реестра (только чтение, аудит)."""

from app.database import SessionLocal
from app.models.project import Project
from app.models.fact_entry import FactEntry
from app.models.audit_log import AuditLog
from app.mcp import registry


def _seed_project() -> int:
    session = SessionLocal()
    try:
        p = Project(
            name="Проект Гамма",
            project_type="smart_contract",
            status="pending_approval",
            business_unit="Финтех",
            metrics={"npv": 1000000, "irr": 22.5},
            smart_contract_data={
                "milestones": [
                    {"title": "MVP", "status": "in_progress", "deadline": "2026-09-01", "rewardRub": 500000, "coins": 100},
                ],
                "curator": "Иван Петров",
                "team": [{"name": "Анна Смирнова"}],
            },
        )
        session.add(p)
        session.commit()
        pid = p.id
        session.add(
            FactEntry(project_id=pid, year=2026, month=6, metric_name="Выручка", plan_value=100.0, fact_value=90.0)
        )
        session.commit()
        return pid
    finally:
        session.close()


def test_list_projects_and_pending():
    pid = _seed_project()
    res = registry.call_tool("list_projects")
    assert res["count"] >= 1
    assert any(p["id"] == pid for p in res["projects"])

    pending = registry.call_tool("list_pending_approvals")
    assert any(p["id"] == pid for p in pending["pending"])


def test_get_project_and_facts_and_milestones():
    pid = _seed_project()

    proj = registry.call_tool("get_project", {"project_id": pid})
    assert proj["name"] == "Проект Гамма"
    assert proj["metrics"]["npv"] == 1000000
    assert proj["milestones_count"] == 1

    facts = registry.call_tool("get_project_facts", {"project_id": pid})
    assert facts["count"] == 1
    row = facts["facts"][0]
    assert row["metric"] == "Выручка"
    assert row["deviation_pct"] == -10.0  # (90-100)/100*100

    ms = registry.call_tool("get_milestones", {"project_id": pid})
    assert ms["count"] == 1
    assert ms["milestones"][0]["title"] == "MVP"


def test_list_upcoming_deadlines_tool():
    import datetime as dt

    session = SessionLocal()
    try:
        soon = (dt.date.today() + dt.timedelta(days=5)).isoformat()
        overdue = (dt.date.today() - dt.timedelta(days=3)).isoformat()
        far = (dt.date.today() + dt.timedelta(days=90)).isoformat()
        p = Project(
            name="Проект Дельта",
            project_type="smart_contract",
            status="approved",
            smart_contract_data={
                "milestones": [
                    {"title": "Этап скоро", "status": "in_progress", "deadline": soon},
                    {"title": "Этап просрочен", "status": "pending", "deadline": overdue},
                    {"title": "Этап далеко", "status": "pending", "deadline": far},
                    {"title": "Этап готов", "status": "paid", "deadline": overdue},
                ],
            },
        )
        session.add(p)
        session.commit()
        pid = p.id
    finally:
        session.close()

    res = registry.call_tool("list_upcoming_deadlines", {"window_days": 30})
    titles = {d["milestone"] for d in res["deadlines"] if d["project_id"] == pid}
    assert "Этап скоро" in titles
    assert "Этап просрочен" in titles          # overdue always included
    assert "Этап далеко" not in titles         # beyond the 30-day window
    assert "Этап готов" not in titles          # completed milestones excluded
    assert res["overdue_count"] >= 1


def test_portfolio_stats_tool():
    _seed_project()
    stats = registry.call_tool("get_portfolio_stats")
    assert "by_status" in stats and "total" in stats
    assert stats["total"] >= 1


def test_unknown_tool_is_audited_error():
    res = registry.call_tool("no_such_tool")
    assert "error" in res
    session = SessionLocal()
    try:
        row = (
            session.query(AuditLog)
            .filter(AuditLog.action == "mcp.tool_call", AuditLog.target_id == "no_such_tool")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None and row.result == "error"
    finally:
        session.close()


def test_tool_call_is_audited_ok():
    registry.call_tool("get_portfolio_stats")
    session = SessionLocal()
    try:
        row = (
            session.query(AuditLog)
            .filter(AuditLog.action == "mcp.tool_call", AuditLog.target_id == "get_portfolio_stats")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None and row.result == "ok"
    finally:
        session.close()
