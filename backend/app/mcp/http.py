"""HTTP-транспорт MCP (Streamable HTTP) с авторизацией по токену.

Эндпоинт ``/api/mcp`` встроен в основное FastAPI-приложение, поэтому проходит
через тот же nginx (``location /api/``) и HTTPS, что и остальной API.

* Доступ — по токену в заголовке ``Authorization: Bearer <токен>``:
  - **личные токены пользователей** (CEO/CFO/менеджер создают их сами в
    профиле, ``services.mcp_token_service``); в аудит пишется id пользователя;
  - **служебные токены** из env ``MCP_HTTP_TOKENS`` (``имя=токен,…``) — для
    интеграций без пользователя; в аудит пишется имя токена.
* Режим stateless + JSON-ответы: сервер не хранит сессии между запросами, так
  что работает при нескольких воркерах uvicorn и за обычным прокси.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import logging
from typing import Optional

from .. import settings_store
from .server import CLIENT_SCOPE_KEY, build_server

logger = logging.getLogger("hermes.mcp")

MCP_HTTP_PATH = "/api/mcp"


class _ClosedStreamNoiseFilter(logging.Filter):
    """Глушит ложную ошибку mcp 1.12.x в stateless-режиме.

    После каждого успешного запроса библиотека пишет ERROR «Error in message
    router» с ``anyio.ClosedResourceError`` — поток уже закрыт штатно. Новые
    версии mcp это исправили, но требуют pydantic>=2.11. Остальные ошибки
    логгера не трогаем.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() == "Error in message router" and record.exc_info:
            exc = record.exc_info[1]
            if type(exc).__name__ == "ClosedResourceError":
                return False
        return True


logging.getLogger("mcp.server.streamable_http").addFilter(_ClosedStreamNoiseFilter())


async def _send_json(send, status: int, payload: dict, headers: Optional[list] = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
    ] + (headers or [])
    await send({"type": "http.response.start", "status": status, "headers": raw_headers})
    await send({"type": "http.response.body", "body": body})


def _bearer_token(scope) -> Optional[str]:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"authorization":
            text = value.decode("latin-1").strip()
            if text[:7].lower() == "bearer ":
                return text[7:].strip() or None
    return None


def authenticate(token: Optional[str], tokens: dict) -> Optional[str]:
    """Вернуть имя клиента по токену (сравнение за постоянное время)."""
    if not token:
        return None
    found = None
    for name, expected in tokens.items():
        if hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            found = name
    return found


def _user_client(raw: Optional[str]) -> Optional[str]:
    """id пользователя (строкой) по личному токену из БД."""
    from ..database import SessionLocal
    from ..services import mcp_token_service

    db = SessionLocal()
    try:
        user = mcp_token_service.authenticate(db, raw)
        return str(user.id) if user is not None else None
    finally:
        db.close()


async def _resolve_client(raw: Optional[str]) -> Optional[str]:
    """Кто обращается: id пользователя (личный токен) или имя служебного токена."""
    if not raw:
        return None
    client = authenticate(raw, settings_store.get_mcp_http_tokens())
    if client is not None:
        return f"svc:{client}"
    import anyio

    return await anyio.to_thread.run_sync(_user_client, raw)


class McpHttpEndpoint:
    """ASGI-приложение эндпоинта ``/api/mcp``.

    Менеджер сессий MCP запускается/останавливается событиями приложения
    (:meth:`startup` / :meth:`shutdown`).
    """

    def __init__(self) -> None:
        self._manager = None
        self._stack: Optional[contextlib.AsyncExitStack] = None

    async def startup(self) -> None:
        try:
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        except ImportError:  # pragma: no cover - зависит от окружения
            logger.warning("Пакет 'mcp' не установлен — HTTP MCP-эндпоинт недоступен")
            return
        manager = StreamableHTTPSessionManager(
            app=build_server(),
            stateless=True,
            json_response=True,
        )
        stack = contextlib.AsyncExitStack()
        await stack.enter_async_context(manager.run())
        self._manager, self._stack = manager, stack

    async def shutdown(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._manager, self._stack = None, None

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":  # pragma: no cover
            return
        client = await _resolve_client(_bearer_token(scope))
        if client is None:
            logger.warning(
                "MCP HTTP: отказ в доступе (неверный или отсутствующий токен)",
                extra={"event": {"path": scope.get("path"), "client": (scope.get("client") or [None])[0]}},
            )
            await _send_json(
                send,
                401,
                {"detail": "Нужен заголовок Authorization: Bearer <токен>"},
                headers=[(b"www-authenticate", b'Bearer realm="invest-mcp"')],
            )
            return

        if self._manager is None:
            await _send_json(send, 503, {"detail": "MCP-сервер не запущен"})
            return

        scope = dict(scope)
        scope[CLIENT_SCOPE_KEY] = client
        await self._manager.handle_request(scope, receive, send)


endpoint = McpHttpEndpoint()
