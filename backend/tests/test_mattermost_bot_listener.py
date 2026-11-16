"""Слушатель бота Hermes: явные ошибки вместо «тихого» молчания."""

import asyncio
import json

import pytest

from app.services import mattermost_bot_service as bot
from app.services import mattermost_service


class _FakeWS:
    def __init__(self, replies):
        self._replies = list(replies)

    async def recv(self):
        if not self._replies:
            await asyncio.sleep(3600)
        return json.dumps(self._replies.pop(0))


def test_auth_ok_after_hello():
    ws = _FakeWS([{"event": "hello", "seq": 0}, {"status": "OK", "seq_reply": 1}])
    asyncio.run(bot._await_auth_reply(ws))


def test_auth_fail_raises_with_reason():
    ws = _FakeWS([{"status": "FAIL", "seq_reply": 1,
                   "error": {"id": "api.web_socket_router.not_authenticated.app_error",
                             "message": "Invalid or expired session"}}])
    with pytest.raises(bot._AuthError, match="Invalid or expired session"):
        asyncio.run(bot._await_auth_reply(ws))


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("MATTERMOST_BASE_URL", "https://mm.example.com")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "tok")


def test_check_bot_reports_rejected_token(configured, monkeypatch):
    monkeypatch.setattr(mattermost_service.httpx, "get", lambda *a, **k: _Resp(401))
    res = mattermost_service.check_bot()
    assert res["ok"] is False and "401" in res["error"]


def test_check_bot_ok(configured, monkeypatch):
    monkeypatch.setattr(mattermost_service.httpx, "get",
                        lambda *a, **k: _Resp(200, {"id": "b1", "username": "hermes"}))
    res = mattermost_service.check_bot()
    assert res["ok"] and res["me"]["username"] == "hermes"


def test_check_bot_not_configured(monkeypatch):
    monkeypatch.delenv("MATTERMOST_BASE_URL", raising=False)
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    assert mattermost_service.check_bot()["ok"] is False


def test_status_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_BOT_STATUS_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(bot, "_last_state", None)
    bot._set_status("auth_failed", "Invalid or expired session")
    st = bot.read_status()
    assert st["state"] == "auth_failed" and "expired" in st["detail"]


def test_listener_starts_even_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_BOT_LOCK_PATH", str(tmp_path / "l.lock"))
    monkeypatch.setattr(bot, "_started", False)
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    started = []

    class _T:
        def __init__(self, target, name, daemon):
            started.append(name)

        def start(self):
            pass

    monkeypatch.setattr(bot.threading, "Thread", _T)
    assert bot.start_bot_listener() is True
    assert started == ["hermes-bot-ws"]
