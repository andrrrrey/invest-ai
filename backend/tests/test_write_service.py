"""Тесты операций на запись, гейта write-инструментов и endpoint аудита."""

import uuid

import pytest
from fastapi import HTTPException

from app import settings_store
from app.database import SessionLocal
from app.models.project import Project
from app.models.fact_entry import FactEntry
from app.models.audit_log import AuditLog
from app.services import write_service
from app.mcp import registry
from app.api.v1.audit import list_audit


def _mk_sc_project() -> int:
    session = SessionLocal()
    try:
        p = Project(
            name=f"СК {uuid.uuid4().hex[:6]}",
            project_type="smart_contract",
            status="approved",
            smart_contract_data={"milestones": [
                {"title": "Этап 1", "status": "in_progress"},
                {"title": "Этап 2", "status": "pending"},
            ]},
        )
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def test_update_fact_persists_and_audits(db_session):
    pid = _mk_sc_project()
    res = write_service.update_fact(
        db_session, pid,
        [{"year": 2026, "month": 6, "metric_name": "Выручка", "plan_value": 100, "fact_value": 80}],
    )
    assert res["updated"] == 1
    row = db_session.query(FactEntry).filter_by(project_id=pid, metric_name="Выручка").first()
    assert row is not None and row.fact_value == 80

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "write.fact", AuditLog.target_id == str(pid))
        .first()
    )
    assert audit is not None and audit.result == "ok"


def test_update_milestone_status_persists(db_session):
    pid = _mk_sc_project()
    res = write_service.update_milestone_status(db_session, pid, 0, "paid")
    assert res["status"] == "paid"

    project = db_session.get(Project, pid)
    assert project.smart_contract_data["milestones"][0]["status"] == "paid"

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "write.milestone", AuditLog.target_id == str(pid))
        .first()
    )
    assert audit is not None


def test_update_milestone_invalid_status_and_index(db_session):
    pid = _mk_sc_project()
    with pytest.raises(HTTPException) as e1:
        write_service.update_milestone_status(db_session, pid, 0, "no-such-status")
    assert e1.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        write_service.update_milestone_status(db_session, pid, 99, "paid")
    assert e2.value.status_code == 404


def test_write_tool_gated_off_by_default(monkeypatch):
    pid = _mk_sc_project()
    monkeypatch.setattr(settings_store, "is_hermes_write_enabled", lambda: False)
    res = registry.call_tool("update_milestone_status", {"project_id": pid, "index": 0, "status": "paid"})
    assert "error" in res
    # Статус не изменился.
    session = SessionLocal()
    try:
        p = session.get(Project, pid)
        assert p.smart_contract_data["milestones"][0]["status"] == "in_progress"
    finally:
        session.close()
    # Write-инструменты не предлагаются агенту, пока режим выключен.
    names = [t["function"]["name"] for t in registry.openai_tools()]
    assert "update_milestone_status" not in names


def test_write_tool_works_when_enabled(monkeypatch):
    pid = _mk_sc_project()
    monkeypatch.setattr(settings_store, "is_hermes_write_enabled", lambda: True)
    res = registry.call_tool("update_milestone_status", {"project_id": pid, "index": 1, "status": "verify"})
    assert res.get("status") == "verify"
    names = [t["function"]["name"] for t in registry.openai_tools()]
    assert "update_fact" in names and "update_milestone_status" in names


def test_audit_endpoint_filters(db_session):
    from app.services import audit_service
    marker = f"test.action.{uuid.uuid4().hex[:6]}"
    audit_service.log_event(action=marker, actor_type="hermes", result="ok", db=db_session)
    db_session.commit()

    out = list_audit(action=marker, db=db_session, _=None)
    assert out["total"] >= 1
    assert any(item["action"] == marker for item in out["items"])
