"""Тесты выгрузки системных логов и экспорта аудита."""

import json
import uuid

from app.services import log_export, email_service, audit_service
from app.api.v1 import audit as audit_api
from app.database import SessionLocal


def _write_log(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_read_logs_filters_by_level_and_text(tmp_path, monkeypatch):
    logfile = tmp_path / "app.log"
    _write_log(logfile, [
        {"ts": "t1", "level": "INFO", "logger": "hermes.request", "msg": "ok"},
        {"ts": "t2", "level": "ERROR", "logger": "hermes.ai", "msg": "boom provider"},
        {"ts": "t3", "level": "WARNING", "logger": "hermes.approval", "msg": "bot not configured"},
    ])
    monkeypatch.setenv("LOG_FILE", str(logfile))

    # Все строки.
    assert len(log_export.read_logs().splitlines()) == 3
    # Только ошибки.
    errs = log_export.read_logs(level="ERROR")
    assert '"level": "ERROR"' in errs and '"level": "INFO"' not in errs
    # WARNING и выше — 2 строки (WARNING + ERROR).
    assert len(log_export.read_logs(level="WARNING").splitlines()) == 2
    # Поиск по подстроке.
    assert "provider" in log_export.read_logs(contains="provider")
    assert log_export.read_logs(contains="provider").count("\n") == 0  # одна строка


def test_read_logs_tail(tmp_path, monkeypatch):
    logfile = tmp_path / "app.log"
    _write_log(logfile, [{"level": "INFO", "msg": str(i)} for i in range(10)])
    monkeypatch.setenv("LOG_FILE", str(logfile))
    out = log_export.read_logs(max_lines=3)
    assert len(out.splitlines()) == 3
    assert '"msg": "9"' in out  # последние строки


def test_export_audit_csv(db_session):
    marker = f"csv.action.{uuid.uuid4().hex[:6]}"
    audit_service.log_event(action=marker, actor_type="hermes", result="ok", db=db_session)
    db_session.commit()

    resp = audit_api.export_audit(action=marker, db=db_session, _=None)
    body = resp.body.decode("utf-8-sig")
    assert "action" in body.splitlines()[0]  # заголовок
    assert marker in body


def test_logs_email_sends_and_audits(monkeypatch, db_session):
    sent = {}
    monkeypatch.setattr(log_export, "read_logs", lambda **kw: '{"level":"ERROR","msg":"x"}')
    monkeypatch.setattr(
        email_service, "send_email_with_attachment",
        lambda to, subject, text_body, attachment_bytes, filename, content_type="text/plain":
            sent.update({"to": to, "bytes": attachment_bytes}),
    )
    req = audit_api.LogsEmailRequest(to="dev@example.com", level="ERROR", lines=100)
    out = audit_api.logs_email(req, _=None)
    assert out["success"] is True
    assert sent["to"] == "dev@example.com"

    session = SessionLocal()
    try:
        from app.models.audit_log import AuditLog
        row = session.query(AuditLog).filter(AuditLog.action == "audit.logs_emailed").order_by(AuditLog.id.desc()).first()
        assert row is not None and row.target_id == "dev@example.com"
    finally:
        session.close()


def test_logs_email_rejects_bad_email(monkeypatch):
    import pytest
    monkeypatch.setattr(log_export, "read_logs", lambda **kw: "x")
    with pytest.raises(Exception):
        audit_api.logs_email(audit_api.LogsEmailRequest(to="not-an-email"), _=None)
