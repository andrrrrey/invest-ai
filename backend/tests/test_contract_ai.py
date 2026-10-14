"""Пункт 10 КП: AI-помощник мастера и карточки контракта."""

import json

from _helpers import client, mk_user, auth, mk_contract, get_project
from app import settings_store
from app.services import ai_service


def _enable_ai(monkeypatch, reply):
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "get_ai_provider", lambda: "anthropic")
    monkeypatch.setattr(settings_store, "get_anthropic_key", lambda: "sk-test")
    calls = []

    def fake_chat(prompt, max_tokens=700, **kw):
        calls.append((prompt, kw.get("action")))
        return reply(prompt) if callable(reply) else reply
    monkeypatch.setattr(ai_service, "_chat", fake_chat)
    return calls


def test_description_and_smart_check(monkeypatch):
    user = mk_user("owner")
    calls = _enable_ai(monkeypatch, lambda p: json.dumps(
        {"shortDescription": "Суть", "businessEffect": "Эффект"} if "shortDescription" in p
        else {"S": True, "M": True, "A": True, "R": False, "T": True, "feedback": "Свяжите с целью"}))
    r = client.post("/api/v1/ai/contract/description", headers=auth(user),
                    json={"name": "DevOps", "business_unit": "IT", "sc_type": "smart"})
    assert r.status_code == 200 and r.json() == {"shortDescription": "Суть", "businessEffect": "Эффект"}
    r = client.post("/api/v1/ai/contract/smart-check", headers=auth(user),
                    json={"milestone": {"name": "Э1", "criteria": "Время деплоя ≤ 10 мин"}})
    data = r.json()
    assert data["R"] is False and data["valid"] is False and "цел" in data["feedback"]
    assert {a for _, a in calls} == {"ai.contract_description", "ai.contract_smart"}


def test_ai_disabled_returns_403(monkeypatch):
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: False)
    user = mk_user("owner")
    r = client.post("/api/v1/ai/contract/summary", headers=auth(user), json={"contract": {}})
    assert r.status_code == 403


def test_bad_ai_json_is_502(monkeypatch):
    _enable_ai(monkeypatch, "не JSON")
    user = mk_user("owner")
    r = client.post("/api/v1/ai/contract/smart-check", headers=auth(user), json={"milestone": {}})
    assert r.status_code == 502


def test_milestone_dispute_and_arbitration_persisted(monkeypatch):
    _enable_ai(monkeypatch, json.dumps({"decision": "partial", "payout_percent": 70, "reasoning": "Частично"}))
    owner = mk_user("owner")
    manager = mk_user("manager")
    pid = mk_contract(owner, "smart", "approved", milestones=[{"name": "Э1", "criteria": "≥10 тикетов"}])
    # Исполнитель сам не подтверждает свой этап.
    r = client.patch(f"/api/v1/projects/{pid}/milestones/0/status", headers=auth(owner), json={"status": "paid"})
    assert r.status_code == 403
    r = client.patch(f"/api/v1/projects/{pid}/milestones/0/status", headers=auth(manager),
                     json={"status": "disputed", "note": "Только 7 тикетов"})
    assert r.status_code == 200
    ms = get_project(pid).smart_contract_data["milestones"][0]
    assert ms["status"] == "disputed" and ms["disputeNote"] == "Только 7 тикетов"
    r = client.post(f"/api/v1/projects/{pid}/milestones/0/arbitration", headers=auth(manager), json={})
    assert r.status_code == 200 and r.json()["payout_percent"] == 70
    assert get_project(pid).smart_contract_data["milestones"][0]["arbitration"]["decision"] == "partial"
