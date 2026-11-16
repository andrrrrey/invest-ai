"""
Standalone MCP-сервер на открытом стандарте для внешних ИИ-клиентов.

Публикует read-only часть реестра инструментов (``registry.TOOL_SPECS``), ту же,
что использует внутренний агент Hermes. Вызовы идут через ``gateway`` —
обезличивание (флаг ``mcp_anonymize_enabled``) и аудит (``actor_type=ai_gateway``).

Два транспорта:

* **stdio** — клиент сам запускает процесс на машине с бэкендом::

      python -m app.mcp.server

* **Streamable HTTP** — эндпоинт ``/api/mcp`` внутри основного приложения
  (см. ``app.mcp.http``), доступ по токену ``Authorization: Bearer <токен>``.

Пакет ``mcp`` импортируется лениво, чтобы его отсутствие не ломало приложение.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from . import gateway

SERVER_NAME = "hermes-invest"
# Ключ ASGI-scope, куда HTTP-слой кладёт имя аутентифицированного клиента.
CLIENT_SCOPE_KEY = "invest_mcp_client"


def _current_client(server) -> Optional[str]:
    """Имя клиента HTTP-запроса (для аудита); для stdio — ``stdio``."""
    try:
        request = server.request_context.request
    except LookupError:
        return "stdio"
    if request is None:
        return "stdio"
    try:
        return request.scope.get(CLIENT_SCOPE_KEY)
    except AttributeError:
        return None


def build_server():
    """Создать MCP-сервер (общий для stdio и HTTP)."""
    from mcp.server.lowlevel import Server
    import mcp.types as mcp_types
    import anyio

    server = Server(SERVER_NAME, instructions=gateway.SERVER_INSTRUCTIONS)

    @server.list_tools()
    async def _list_tools():
        return [
            mcp_types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["parameters"],
            )
            for spec in gateway.list_tool_specs()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        actor_id = _current_client(server)
        # Инструменты синхронные (SQLAlchemy) — не блокируем event loop.
        result = await anyio.to_thread.run_sync(
            lambda: gateway.call_external_tool(name, arguments, actor_id=actor_id)
        )
        return [
            mcp_types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, default=str),
            )
        ]

    return server


def main() -> None:
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise SystemExit(
            "Пакет 'mcp' не установлен. Установите его для запуска MCP-сервера: "
            "pip install -r requirements.txt"
        ) from exc

    server = build_server()

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
