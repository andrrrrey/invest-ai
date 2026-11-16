"""Внешний MCP: обезличивание (стабильные метки) и HTTP-транспорт с токеном."""

import json
import re

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.mcp import gateway
from app.mcp.http import authenticate
from app import settings_store

_LABEL = re.compile(r"\[PROJECT_[0-9A-F]+\]")


def _seed(name="Проект Сигма", owner="Мария Козлова") -> int:
    s = SessionLocal()
    try:
        p = Project(
            name=name,
            project_type="smart_contract",
            status="pending_approval",
            business_unit="Ритейл Сигма",
            owner=owner,
            metrics={"npv": 777000},
        )
        s.add(p)
        s.commit()
        return p.id
    finally:
        s.close()


def test_result_is_anonymized_and_numbers_kept():
    pid = _seed()
    res = gateway.call_external_tool("get_project", {"project_id": pid}, actor_id="t")
    dumped = json.dumps(res, ensure_ascii=False)
    assert "Проект Сигма" not in dumped
    assert "Мария Козлова" not in dumped
    assert "Ритейл Сигма" not in dumped
    assert res["id"] == pid
    assert res["metrics"]["npv"] == 777000
    assert _LABEL.fullmatch(res["name"])


def test_labels_are_stable_and_resolvable_after_reset():
    pid = _seed(name="Проект Омега", owner="Пётр Орлов")
    first = gateway.call_external_tool("get_project", {"project_id": pid})["name"]
    # «Перезапуск»: сопоставление в памяти потеряно, метка та же и находится.
    gateway._reset_anonymizer()
    again = gateway.call_external_tool("get_project", {"project_id": pid})["name"]
    assert first == again
    found = gateway.call_external_tool("find_projects", {"query": first})
    assert any(p["id"] == pid for p in found["projects"])


def test_audit_stores_masked_args_only():
    pid = _seed(name="Проект Тета", owner="Олег Сидоров")
    label = gateway.call_external_tool("get_project", {"project_id": pid})["name"]
    gateway.call_external_tool("find_projects", {"query": label}, actor_id="auditcheck")
    s = SessionLocal()
    try:
        row = (
            s.query(AuditLog)
            .filter(AuditLog.actor_id == "auditcheck")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row.actor_type == "ai_gateway"
        assert "Проект Тета" not in json.dumps(row.meta, ensure_ascii=False)
        assert row.anonymized is True
    finally:
        s.close()


def test_anonymization_can_be_disabled():
    pid = _seed(name="Проект Каппа", owner="Нина Белова")
    settings_store.set_mcp_anonymize_enabled(False)
    try:
        res = gateway.call_external_tool("get_project", {"project_id": pid})
        assert res["name"] == "Проект Каппа"
    finally:
        settings_store.set_mcp_anonymize_enabled(True)


def test_write_tools_not_available_externally():
    settings_store.set_hermes_write_enabled(True)
    try:
        names = {s["name"] for s in gateway.list_tool_specs()}
        assert "update_fact" not in names
        res = gateway.call_external_tool("add_comment", {"project_id": 1, "text": "x"})
        assert "error" in res
    finally:
        settings_store.set_hermes_write_enabled(False)


def test_token_parsing_and_auth(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_TOKENS", "claude=abc, plain ,")
    tokens = settings_store.get_mcp_http_tokens()
    assert tokens == {"claude": "abc", "client2": "plain"}
    assert authenticate("abc", tokens) == "claude"
    assert authenticate("plain", tokens) == "client2"
    assert authenticate("wrong", tokens) is None
    assert authenticate(None, tokens) is None


def _rpc(client, payload, token="tok-123"):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/api/mcp", json=payload, headers=headers)


def test_http_endpoint(monkeypatch):
    from app.main import app

    pid = _seed(name="Проект Дельта-HTTP", owner="Анна Лебедева")
    monkeypatch.setenv("MCP_HTTP_TOKENS", "tester=tok-123")
    with TestClient(app) as client:
        assert _rpc(client, {}, token=None).status_code == 401
        assert _rpc(client, {}, token="bad").status_code == 401

        init = _rpc(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "1"}},
        })
        assert init.status_code == 200
        assert init.json()["result"]["serverInfo"]["name"] == "hermes-invest"

        listed = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert "get_project" in names and "update_fact" not in names

        called = _rpc(client, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_project", "arguments": {"project_id": pid}},
        })
        text = called.json()["result"]["content"][0]["text"]
        assert "Дельта-HTTP" not in text
        assert json.loads(text)["id"] == pid

    monkeypatch.delenv("MCP_HTTP_TOKENS")
    with TestClient(app) as client:
        # Без служебных токенов эндпоинт всё равно работает (личные токены),
        # но без токена — 401.
        assert _rpc(client, {}).status_code == 401


_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "pytest", "version": "1"}},
}


def test_personal_tokens_lifecycle(monkeypatch):
    from app.main import app
    from app.models.user import User
    from tests._helpers import mk_user, auth

    monkeypatch.delenv("MCP_HTTP_TOKENS", raising=False)
    manager = mk_user("manager")
    owner = mk_user("owner")
    cfo = mk_user("cfo")

    with TestClient(app) as client:
        # Заявителю (owner) создавать токены нельзя.
        r = client.post("/api/v1/mcp-tokens/", json={"name": "x"}, headers=auth(owner))
        assert r.status_code == 403
        assert client.get("/api/v1/mcp-tokens/", headers=auth(owner)).json()["allowed"] is False

        # Менеджер создаёт токен — он возвращается один раз.
        r = client.post("/api/v1/mcp-tokens/", json={"name": "Мой Claude"}, headers=auth(manager))
        assert r.status_code == 200
        created = r.json()
        raw = created["token"]
        assert raw.startswith("imcp_")
        listed = client.get("/api/v1/mcp-tokens/", headers=auth(manager)).json()
        assert listed["allowed"] is True
        assert [t["name"] for t in listed["items"]] == ["Мой Claude"]
        assert "token" not in listed["items"][0]

        # Токен работает на /api/mcp сразу, без перезапуска.
        assert _rpc(client, _INIT, token=raw).status_code == 200
        called = _rpc(client, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "list_pending_approvals", "arguments": {}},
        }, token=raw)
        assert called.status_code == 200

        # В аудит пишется id пользователя.
        s = SessionLocal()
        try:
            row = (
                s.query(AuditLog)
                .filter(AuditLog.action == "mcp.tool_call", AuditLog.target_id == "list_pending_approvals")
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert row.actor_type == "ai_gateway" and row.actor_id == str(manager)
        finally:
            s.close()

        # Чужой пользователь (не CFO) не может отозвать токен; CFO видит и может.
        other = mk_user("ceo")
        assert client.delete(f"/api/v1/mcp-tokens/{created['id']}", headers=auth(other)).status_code == 404
        everyone = client.get("/api/v1/mcp-tokens/?all=true", headers=auth(cfo)).json()["items"]
        assert any(t["id"] == created["id"] for t in everyone)
        assert client.get("/api/v1/mcp-tokens/?all=true", headers=auth(manager)).status_code == 403

        # Отзыв — доступ пропадает сразу.
        assert client.delete(f"/api/v1/mcp-tokens/{created['id']}", headers=auth(manager)).status_code == 200
        assert _rpc(client, _INIT, token=raw).status_code == 401

        # Деактивированный пользователь / смена роли на owner — токен не работает.
        raw2 = client.post("/api/v1/mcp-tokens/", json={"name": "2"}, headers=auth(manager)).json()["token"]
        assert _rpc(client, _INIT, token=raw2).status_code == 200
        s = SessionLocal()
        try:
            u = s.get(User, manager)
            u.role = "owner"
            s.commit()
        finally:
            s.close()
        assert _rpc(client, _INIT, token=raw2).status_code == 401
