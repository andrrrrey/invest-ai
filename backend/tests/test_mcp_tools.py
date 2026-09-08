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


def test_get_project_returns_operational_content():
    session = SessionLocal()
    try:
        p = Project(
            name="Найм DBA-инженера тест",
            project_type="operational",
            status="approved",
            description=None,
            financial_model={
                "op_category": "R&D",
                "op_mvz_main": "7", "op_mvz_sub1": "7.1", "op_mvz_sub2": "7.1.1",
                "op_investment_type": "Защита и устойчивость",
                "op_requested_resource": "<p>Запрашиваю ФОТ, стоимость <b>330 000</b> рублей</p>",
                "op_investment_thesis": "<ul><li>рост техдолга</li><li>риск оттока</li></ul>",
                "op_metrics": "0 падений",
            },
            value_score_data={"total": 31, "band": "Efficiency Play"},
            decision_route="efficiency_play",
        )
        session.add(p)
        session.commit()
        pid = p.id
    finally:
        session.close()

    res = registry.call_tool("get_project", {"project_id": pid})
    content = res["content"]
    # HTML вычищен, содержание доступно.
    assert "Запрашиваю ФОТ" in content["requested_resource"]
    assert "<" not in content["requested_resource"]
    assert "рост техдолга" in content["investment_thesis"]
    assert content["mvz"] == "7 / 7.1 / 7.1.1"
    assert content["category"] == "R&D"
    assert res["value_score"]["total"] == 31


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


def _seed_ranked_projects() -> dict:
    """Три investment-проекта с уникально большими NPV (чтобы гарантированно
    были в топе, вне зависимости от прочих сидов) и один operational без NPV."""
    session = SessionLocal()
    try:
        a = Project(name="Ранг A", project_type="investment", status="approved",
                    metrics={"npv": 9_000_000_000_000, "irr": 30, "dpp": 5})
        b = Project(name="Ранг B", project_type="investment", status="approved",
                    metrics={"npv": 8_000_000_000_000, "irr": 20, "dpp": 3})
        c = Project(name="Ранг C", project_type="investment", status="approved",
                    metrics={"npv": 7_000_000_000_000, "irr": 25, "dpp": 8})
        op = Project(name="Ранг OP", project_type="operational", status="approved",
                     metrics={})  # у операционной заявки NPV не рассчитывается
        session.add_all([a, b, c, op])
        session.commit()
        return {"a": a.id, "b": b.id, "c": c.id, "op": op.id}
    finally:
        session.close()


def test_rank_projects_sorts_deterministically_by_npv():
    ids = _seed_ranked_projects()
    res = registry.call_tool("rank_projects", {"metric": "npv", "top_n": 3, "project_type": "investment"})
    top_ids = [p["id"] for p in res["projects"]]
    # Детерминированный порядок по убыванию NPV: A > B > C.
    assert top_ids == [ids["a"], ids["b"], ids["c"]]
    assert [p["rank"] for p in res["projects"]] == [1, 2, 3]
    assert res["projects"][0]["npv"] == 9_000_000_000_000
    assert res["order"] == "desc"


def test_rank_projects_excludes_projects_without_metric():
    ids = _seed_ranked_projects()
    res = registry.call_tool("rank_projects", {"metric": "npv", "project_type": "operational", "top_n": 50})
    ranked_ids = [p["id"] for p in res["projects"]]
    # Операционная заявка без NPV НЕ попадает в рейтинг и не показывается с «0».
    assert ids["op"] not in ranked_ids
    assert res["without_metric_count"] >= 1


def test_rank_projects_default_order_and_override():
    # Для DPP «лучше» — меньше, поэтому по умолчанию сортировка по возрастанию.
    assert registry.call_tool("rank_projects", {"metric": "dpp"})["order"] == "asc"
    assert registry.call_tool("rank_projects", {"metric": "npv"})["order"] == "desc"
    # Явное направление переопределяет умолчание.
    assert registry.call_tool("rank_projects", {"metric": "npv", "order": "asc"})["order"] == "asc"


def test_rank_projects_unknown_metric_errors():
    res = registry.call_tool("rank_projects", {"metric": "wat"})
    assert "error" in res
