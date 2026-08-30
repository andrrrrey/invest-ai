"""Тест агентного цикла Hermes с фейковым LLM: обезличивание и tool-calling."""

import types

from app import settings_store
from app.database import SessionLocal
from app.models.project import Project
from app.models.audit_log import AuditLog
from app.services import hermes_agent


class _FakeMsg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.type = "function"
        self.function = types.SimpleNamespace(name=name, arguments=arguments)


class _FakeResp:
    def __init__(self, message):
        self.choices = [types.SimpleNamespace(message=message)]


class _FakeCompletions:
    def __init__(self, script, captured):
        self._script = script
        self._captured = captured
        self._i = 0

    def create(self, **kwargs):
        self._captured.append(kwargs)
        msg = self._script[self._i]
        self._i += 1
        return _FakeResp(msg)


class _FakeClient:
    def __init__(self, script, captured):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(script, captured))


def _seed_named_project(name: str) -> int:
    session = SessionLocal()
    try:
        p = Project(name=name, project_type="investment", status="draft")
        session.add(p)
        session.commit()
        return p.id
    finally:
        session.close()


def test_agent_masks_outbound_and_restores_and_uses_tools(monkeypatch):
    secret = "Секрет Альфа Проект"
    _seed_named_project(secret)

    captured = []
    script = [
        _FakeMsg(tool_calls=[_FakeToolCall("c1", "list_projects", "{}")]),
        _FakeMsg(content="Проект [PROJECT_1] находится в статусе draft."),
    ]

    monkeypatch.setattr(
        hermes_agent, "_client_and_model",
        lambda: (_FakeClient(script, captured), "test-model", "routerai"),
    )
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: True)

    answer = hermes_agent.ask(f"Каков статус проекта «{secret}»?", actor_id="tester")

    # Финальный ответ пользователю — с восстановленным реальным названием.
    assert secret in answer

    # Во ВСЕХ исходящих во внешний ИИ сообщениях нет реального названия.
    for call in captured:
        for message in call["messages"]:
            content = message.get("content") or ""
            assert secret not in content, "конфиденциальное название утекло во внешний ИИ"
    # Инструменты действительно предлагались модели.
    assert captured[0].get("tools")

    # Ответ зафиксирован в аудите.
    session = SessionLocal()
    try:
        row = (
            session.query(AuditLog)
            .filter(AuditLog.action == "hermes.answer")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None and row.result == "ok" and row.anonymized is True
    finally:
        session.close()


def test_agent_unmasks_tool_arguments_for_find_projects(monkeypatch):
    """Регресс: модель вызывает find_projects с меткой [PROJECT_1] (т.к. вопрос
    обезличен) — аргумент должен деобезличиваться, иначе поиск не находит проект
    и агент упирается в лимит шагов."""
    secret = "Найм DBA-инженера тест"
    pid = _seed_named_project(secret)

    captured = []
    # Модель «видит» только метку и передаёт её как query.
    script = [
        _FakeMsg(tool_calls=[_FakeToolCall("c1", "find_projects", '{"query": "[PROJECT_1]"}')]),
        _FakeMsg(content="Проект [PROJECT_1] найден, статус draft."),
    ]

    captured_tool_results = {}
    real_find = hermes_agent.registry.call_tool

    def _spy_call_tool(name, arguments=None, **kw):
        res = real_find(name, arguments, **kw)
        if name == "find_projects":
            captured_tool_results["find"] = (arguments, res)
        return res

    monkeypatch.setattr(hermes_agent.registry, "call_tool", _spy_call_tool)
    monkeypatch.setattr(
        hermes_agent, "_client_and_model",
        lambda: (_FakeClient(script, captured), "test-model", "routerai"),
    )
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: True)

    answer = hermes_agent.ask(f"расскажи про проект «{secret}»", actor_id="tester")

    # find_projects получил РЕАЛЬНОЕ название (деобезличенный аргумент) и нашёл проект.
    exec_args, res = captured_tool_results["find"]
    assert exec_args["query"] == secret
    assert any(p["id"] == pid for p in res["projects"])
    # Финальный ответ восстановлен.
    assert secret in answer


def test_agent_forces_final_answer_when_steps_exhausted(monkeypatch):
    """Если модель всё время зовёт инструменты и не даёт текст, агент делает
    принудительный финальный вызов без инструментов и всё равно отвечает."""
    _seed_named_project("Проект для форс-ответа")

    captured = []
    # На каждом из шагов — только вызов инструмента, затем принудительный финал.
    script = [_FakeMsg(tool_calls=[_FakeToolCall(f"c{i}", "list_projects", "{}")]) for i in range(3)]
    script.append(_FakeMsg(content="Итоговый ответ по портфелю."))

    monkeypatch.setattr(
        hermes_agent, "_client_and_model",
        lambda: (_FakeClient(script, captured), "test-model", "routerai"),
    )
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: False)

    answer = hermes_agent.ask("сводка по портфелю", actor_id="tester", max_steps=3)
    assert answer == "Итоговый ответ по портфелю."
    # Последний вызов был без инструментов (tool_choice="none").
    assert captured[-1].get("tool_choice") == "none"


def test_agent_includes_history_before_question(monkeypatch):
    """История диалога добавляется перед текущим вопросом (и обезличивается)."""
    captured = []
    script = [_FakeMsg(content="Ответ с учётом контекста.")]
    monkeypatch.setattr(
        hermes_agent, "_client_and_model",
        lambda: (_FakeClient(script, captured), "test-model", "routerai"),
    )
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: False)

    history = [
        {"role": "user", "content": "Что со статусом?"},
        {"role": "assistant", "content": "Проект в статусе draft."},
    ]
    hermes_agent.ask("а бюджет?", actor_id="tester", history=history)

    msgs = captured[0]["messages"]
    # system, 2 истории, текущий вопрос
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == "Что со статусом?"
    assert msgs[2]["role"] == "assistant" and msgs[2]["content"] == "Проект в статусе draft."
    assert msgs[3]["content"] == "а бюджет?"


def test_agent_blocked_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: False)
    import pytest

    with pytest.raises(ValueError):
        hermes_agent.ask("сводка по портфелю")
