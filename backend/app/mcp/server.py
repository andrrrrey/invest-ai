"""
Standalone MCP-сервер на открытом стандарте (транспорт stdio).

Публикует тот же реестр инструментов (``registry.TOOL_SPECS``), что использует
внутренний агент Hermes, — так внешние MCP-совместимые ИИ-клиенты могут
подключаться без переделки системы. Пакет ``mcp`` импортируется лениво, чтобы
отсутствие зависимости не ломало основное приложение.

Запуск:  python -m app.mcp.server
"""

from __future__ import annotations

import asyncio
import json

from . import registry


def main() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as mcp_types
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise SystemExit(
            "Пакет 'mcp' не установлен. Установите его для запуска MCP-сервера: "
            "pip install mcp"
        ) from exc

    server = Server("hermes-invest")

    @server.list_tools()
    async def _list_tools():
        return [
            mcp_types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["parameters"],
            )
            for spec in registry.TOOL_SPECS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        result = registry.call_tool(name, arguments, actor_type="ai_gateway")
        return [
            mcp_types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, default=str),
            )
        ]

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
