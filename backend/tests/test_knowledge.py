"""Тесты базы знаний Hermes: CRUD, семантический/keyword-поиск, pinned-блок,
MCP-инструмент, гейт флага knowledge_enabled и доступ к API (только CFO)."""

import types

import pytest

from app import settings_store
from app.database import SessionLocal
from app.services import knowledge_service, ai_service
from app.mcp import registry
from app.api.v1 import knowledge as knowledge_api
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdate, KnowledgeSearchRequest


def _clear(db):
    from app.models.knowledge import KnowledgeEntry
    db.query(KnowledgeEntry).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        _clear(session)
        yield session
    finally:
        _clear(session)
        session.close()


def _no_embeddings(monkeypatch):
    """Заставить эмбеддинги быть недоступными → keyword-фолбэк."""
    def _raise(*a, **k):
        raise ai_service.EmbeddingsUnavailable("нет ключа")
    monkeypatch.setattr(ai_service, "embed_texts", _raise)


def _fake_embeddings(monkeypatch, mapping):
    """Детерминированные векторы: mapping — по подстроке в тексте → вектор."""
    def _embed(texts, **k):
        out = []
        for t in texts:
            vec = None
            for needle, v in mapping.items():
                if needle in t:
                    vec = v
                    break
            out.append(vec or [0.0, 0.0, 1.0])
        return out
    monkeypatch.setattr(ai_service, "embed_texts", _embed)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_update_delete_keyword_fallback(db, monkeypatch):
    _no_embeddings(monkeypatch)
    e = knowledge_service.create_entry(
        db, title="МВЗ", content="МВЗ — место возникновения затрат.", tags=["глоссарий"], pinned=False,
    )
    assert e.id is not None
    assert e.embedding is None  # эмбеддинги недоступны — вектор не посчитан

    items = knowledge_service.list_entries(db)
    assert any(it["id"] == e.id for it in items)

    knowledge_service.update_entry(db, e, title="МВЗ (термин)", pinned=True)
    assert db.get(type(e), e.id).pinned is True

    knowledge_service.delete_entry(db, e)
    assert db.get(type(e), e.id) is None


def test_keyword_search_finds_entry(db, monkeypatch):
    _no_embeddings(monkeypatch)
    knowledge_service.create_entry(db, title="IRR", content="Внутренняя норма доходности проекта.")
    res = knowledge_service.search(db, "доходности", top_k=5)
    assert res and res[0]["match"] == "keyword"
    assert "IRR" == res[0]["title"]


# ── Семантический поиск ─────────────────────────────────────────────────────────

def test_semantic_search_ranks_by_cosine(db, monkeypatch):
    # Записи получают ортогональные векторы по ключевому слову в контенте.
    _fake_embeddings(monkeypatch, {
        "дедлайн": [1.0, 0.0, 0.0],
        "бюджет": [0.0, 1.0, 0.0],
        "__query_deadline__": [0.9, 0.1, 0.0],
    })
    knowledge_service.create_entry(db, title="Дедлайны", content="Правила про дедлайн майлстоунов.")
    knowledge_service.create_entry(db, title="Бюджет", content="Правила про бюджет портфеля.")

    # Запрос ближе к «дедлайн».
    monkeypatch.setattr(ai_service, "embed_texts", lambda texts, **k: [[0.9, 0.1, 0.0]])
    res = knowledge_service.search(db, "что там по срокам", top_k=5)
    assert res and res[0]["match"] == "semantic"
    assert res[0]["title"] == "Дедлайны"


def test_semantic_falls_back_to_keyword_when_query_embed_fails(db, monkeypatch):
    _fake_embeddings(monkeypatch, {"термин": [1.0, 0.0, 0.0]})
    knowledge_service.create_entry(db, title="Термин", content="Некий термин компании.")
    # Теперь эмбеддинг запроса падает — должен сработать keyword-фолбэк.
    def _raise(*a, **k):
        raise ai_service.EmbeddingsUnavailable("сбой")
    monkeypatch.setattr(ai_service, "embed_texts", _raise)
    res = knowledge_service.search(db, "термин", top_k=5)
    assert res and res[0]["match"] == "keyword"


# ── Pinned-блок ──────────────────────────────────────────────────────────────

def test_pinned_block_only_active_pinned(db, monkeypatch):
    _no_embeddings(monkeypatch)
    knowledge_service.create_entry(db, title="P1", content="Закреплено", pinned=True)
    knowledge_service.create_entry(db, title="P2", content="Не закреплено", pinned=False)
    e3 = knowledge_service.create_entry(db, title="P3", content="Закреплено но выключено", pinned=True)
    knowledge_service.update_entry(db, e3, is_active=False)

    block = knowledge_service.pinned_block(db)
    assert "P1: Закреплено" in block
    assert "P2" not in block
    assert "P3" not in block


# ── MCP-инструмент и гейт флага ─────────────────────────────────────────────────

def test_search_knowledge_tool_gated_by_flag(monkeypatch):
    monkeypatch.setattr(settings_store, "is_knowledge_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_hermes_write_enabled", lambda: False)
    names = [t["function"]["name"] for t in registry.openai_tools()]
    assert "search_knowledge" in names

    monkeypatch.setattr(settings_store, "is_knowledge_enabled", lambda: False)
    names = [t["function"]["name"] for t in registry.openai_tools()]
    assert "search_knowledge" not in names


def test_search_knowledge_tool_call(db, monkeypatch):
    _no_embeddings(monkeypatch)
    knowledge_service.create_entry(db, title="Регламент", content="Согласуют CFO и менеджер.")
    res = registry.call_tool("search_knowledge", {"query": "менеджер"})
    assert res["count"] >= 1
    assert res["results"][0]["title"] == "Регламент"


# ── API (только CFO) ───────────────────────────────────────────────────────────

class _User:
    role = "cfo"
    email = "cfo@example.com"


def test_api_crud_flow(db, monkeypatch):
    _no_embeddings(monkeypatch)
    user = _User()
    created = knowledge_api.create_knowledge(
        KnowledgeCreate(title="API", content="через эндпоинт", tags=["t"], pinned=True), db=db, user=user
    )
    assert created["title"] == "API" and created["pinned"] is True

    listed = knowledge_api.list_knowledge(db=db, _=user)
    assert any(it["id"] == created["id"] for it in listed["items"])

    updated = knowledge_api.update_knowledge(
        created["id"], KnowledgeUpdate(content="обновлено"), db=db, user=user
    )
    assert updated["content"] == "обновлено"

    found = knowledge_api.search_knowledge(KnowledgeSearchRequest(query="обновлено"), db=db, _=user)
    assert found["results"]

    knowledge_api.delete_knowledge(created["id"], db=db, user=user)
    listed2 = knowledge_api.list_knowledge(db=db, _=user)
    assert not any(it["id"] == created["id"] for it in listed2["items"])


# ── Интеграция с промптом агента ─────────────────────────────────────────────────

def test_agent_injects_pinned_knowledge(db, monkeypatch):
    _no_embeddings(monkeypatch)
    knowledge_service.create_entry(
        db, title="Глоссарий", content="NPV — чистая приведённая стоимость.", pinned=True
    )

    from app.services import hermes_agent

    captured = []

    class _Resp:
        def __init__(self, msg):
            self.choices = [types.SimpleNamespace(message=msg)]

    class _Completions:
        def create(self, **kwargs):
            captured.append(kwargs)
            return _Resp(types.SimpleNamespace(content="Готово.", tool_calls=None))

    class _Client:
        chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setattr(hermes_agent, "_client_and_model", lambda: (_Client(), "test-model", "routerai"))
    monkeypatch.setattr(settings_store, "is_ai_enabled", lambda: True)
    monkeypatch.setattr(settings_store, "is_anonymize_enabled", lambda: False)
    monkeypatch.setattr(settings_store, "is_knowledge_enabled", lambda: True)

    hermes_agent.ask("Что такое NPV?", actor_id="tester")

    system_msg = captured[0]["messages"][0]["content"]
    assert "Знания компании" in system_msg
    assert "NPV — чистая приведённая стоимость." in system_msg
