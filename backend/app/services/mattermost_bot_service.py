"""
Слушатель обычных сообщений бота Hermes в Mattermost (WebSocket).

Slash-команда (`/hermes ...`) отвечает синхронно через REST-эндпоинт. Но на
обычные сообщения (личные сообщения боту или @упоминания в канале) Mattermost
slash/webhook не срабатывает — нужен постоянный слушатель WebSocket API бота.

Этот сервис поднимает фоновый поток, подключается к `/api/v4/websocket`,
слушает события ``posted`` и на подходящие сообщения отвечает тем же агентом
Hermes, что и slash-команда. Ответ уходит в тот же канал (в тред).

Особенности эксплуатации:
- Бэкенд запускается несколькими воркерами uvicorn — слушатель должен работать
  ТОЛЬКО в одном процессе, иначе будут дубли ответов. Для этого используется
  межпроцессная файловая блокировка (fcntl).
- Всё изолировано: любая ошибка логируется и не влияет на основное приложение.
- Свои же сообщения и сообщения других ботов игнорируются (защита от петель).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Optional

from .. import settings_store
from . import mattermost_service, hermes_agent

logger = logging.getLogger("hermes.bot_ws")

# Типы каналов Mattermost.
_CHANNEL_DIRECT = "D"

_started = False
_lock_handle = None  # держим файловый дескриптор блокировки на всё время жизни


# ── Разбор входящего события (чистая функция — покрыта тестами) ────────────────

def parse_incoming(event: dict, bot_user_id: str, bot_username: str) -> Optional[dict]:
    """Решить, нужно ли отвечать на событие, и извлечь вопрос.

    Возвращает ``{"channel_id", "root_id", "text", "sender"}`` для сообщений,
    на которые бот должен ответить, иначе ``None``.

    Отвечаем на:
      • личные сообщения боту (channel_type == 'D');
      • @упоминания бота в любом канале (по mentions или по тексту @username).
    Игнорируем: свои сообщения, сообщения ботов, системные посты, пустой текст.
    """
    if not event or event.get("event") != "posted":
        return None
    data = event.get("data") or {}

    raw_post = data.get("post")
    if not raw_post:
        return None
    try:
        post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
    except (json.JSONDecodeError, TypeError):
        return None

    # Системные сообщения (join/leave и т.п.) пропускаем.
    if (post.get("type") or "").startswith("system_"):
        return None

    # Свои сообщения и сообщения ботов — игнорируем (защита от петель).
    if bot_user_id and post.get("user_id") == bot_user_id:
        return None
    props = post.get("props") or {}
    if str(props.get("from_bot", "")).lower() == "true":
        return None

    text = (post.get("message") or "").strip()
    if not text:
        return None

    channel_type = data.get("channel_type")

    # @упоминания: список id из события или @username в тексте.
    mentioned = False
    raw_mentions = data.get("mentions")
    if raw_mentions:
        try:
            ids = json.loads(raw_mentions) if isinstance(raw_mentions, str) else raw_mentions
            mentioned = bot_user_id in ids
        except (json.JSONDecodeError, TypeError):
            mentioned = False
    mention_tag = f"@{bot_username}" if bot_username else None
    if not mentioned and mention_tag and mention_tag.lower() in text.lower():
        mentioned = True

    is_direct = channel_type == _CHANNEL_DIRECT
    if not (is_direct or mentioned):
        return None

    # Убираем упоминание бота из текста вопроса.
    if mention_tag:
        text = text.replace(mention_tag, "").strip()
    if not text:
        return None

    return {
        "channel_id": post.get("channel_id"),
        # Отвечаем в тред: если пост уже в треде — в его корень, иначе к самому посту.
        "root_id": post.get("root_id") or post.get("id"),
        # Корень треда, если сообщение УЖЕ в треде (для памяти диалога).
        "thread_root": post.get("root_id") or "",
        "channel_type": channel_type,
        "post_id": post.get("id"),
        "text": text,
        "sender": data.get("sender_name") or post.get("user_id") or "mattermost",
        "user_id": post.get("user_id"),
    }


# ── Память диалога ────────────────────────────────────────────────────────────

_HISTORY_LIMIT = 10


def _posts_ascending(data: dict) -> list:
    """Из ответа Mattermost {order, posts} вернуть посты в хронологическом порядке."""
    posts = (data or {}).get("posts") or {}
    rows = list(posts.values())
    rows.sort(key=lambda p: p.get("create_at") or 0)
    return rows


def build_history(parsed: dict, bot_user_id: str, limit: int = _HISTORY_LIMIT) -> list:
    """Собрать историю диалога для агента: список {role, content}.

    Источник: тред (если сообщение в треде) либо последние посты канала (DM).
    Текущее сообщение исключается. Роли: сообщения бота → assistant, прочие → user.
    """
    thread_root = parsed.get("thread_root")
    if thread_root:
        data = mattermost_service.get_thread_posts(thread_root)
    else:
        data = mattermost_service.get_channel_posts(parsed.get("channel_id"), per_page=limit + 5)
    if not data:
        return []

    history = []
    for p in _posts_ascending(data):
        if p.get("id") == parsed.get("post_id"):
            continue  # текущее сообщение
        if (p.get("type") or "").startswith("system_"):
            continue
        msg = (p.get("message") or "").strip()
        if not msg:
            continue  # карточки/вложения без текста пропускаем
        role = "assistant" if p.get("user_id") == bot_user_id else "user"
        history.append({"role": role, "content": msg})
    return history[-limit:]


# ── WebSocket-цикл ────────────────────────────────────────────────────────────

def _ws_url() -> Optional[str]:
    base = (settings_store.get_mattermost_base_url() or "").rstrip("/")
    if not base:
        return None
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/api/v4/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/api/v4/websocket"
    return "wss://" + base + "/api/v4/websocket"


async def _typing_loop(ws, next_seq, channel_id: str, parent_id: str) -> None:
    """Периодически слать индикатор «печатает…», пока бот думает.

    Индикатор в Mattermost гаснет через несколько секунд, поэтому повторяем."""
    try:
        while True:
            await ws.send(json.dumps({
                "action": "user_typing",
                "seq": next_seq(),
                "data": {"channel_id": channel_id, "parent_id": parent_id or ""},
            }))
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _handle_event(event: dict, bot_user_id: str, bot_username: str, ws, next_seq) -> None:
    parsed = parse_incoming(event, bot_user_id, bot_username)
    if not parsed:
        return

    # Показать «печатает…» на время обдумывания (thread-safe: параллельно с агентом).
    typing = asyncio.create_task(
        _typing_loop(ws, next_seq, parsed["channel_id"], parsed.get("thread_root") or "")
    )
    try:
        actor_role = await asyncio.to_thread(
            mattermost_service.resolve_system_role, parsed.get("user_id")
        )
        history = await asyncio.to_thread(build_history, parsed, bot_user_id)
        # Агент — синхронный и делает блокирующие HTTP-вызовы, поэтому уводим
        # его в поток, чтобы не блокировать приём WebSocket-сообщений.
        answer = await asyncio.to_thread(
            lambda: hermes_agent.ask(
                parsed["text"], actor_id=str(parsed["sender"]),
                actor_role=actor_role, history=history,
            )
        )
    except Exception as exc:  # уже залогировано/зааудировано в агенте
        answer = f"Не удалось получить ответ: {exc}"
    finally:
        typing.cancel()
        try:
            await typing
        except Exception:
            pass

    if answer:
        await asyncio.to_thread(
            mattermost_service.post_to_channel,
            parsed["channel_id"], answer, parsed["root_id"],
        )


async def _run_once() -> None:
    """Одно подключение к WebSocket: авторизация и цикл приёма событий."""
    import websockets  # ленивый импорт (идёт с uvicorn[standard])

    url = _ws_url()
    token = settings_store.get_mattermost_bot_token()
    if not url or not token:
        raise RuntimeError("Mattermost bot не настроен (нет URL или токена)")

    me = mattermost_service.get_me() or {}
    bot_user_id = me.get("id") or ""
    bot_username = me.get("username") or ""

    # Возрастающий seq для исходящих WS-действий (auth=1, дальше typing и т.п.).
    _seq = {"n": 1}

    def next_seq() -> int:
        _seq["n"] += 1
        return _seq["n"]

    async with websockets.connect(url, max_size=2**22, ping_interval=30, ping_timeout=20) as ws:
        # Авторизация бота.
        await ws.send(json.dumps({
            "seq": 1,
            "action": "authentication_challenge",
            "data": {"token": token},
        }))
        logger.info("Hermes bot WebSocket подключён (%s)", bot_username or "bot")
        async for raw in ws:
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            # Реагируем только когда чат-режим включён (можно выключить в Настройках).
            if not settings_store.is_hermes_chat_enabled():
                continue
            try:
                await _handle_event(event, bot_user_id, bot_username, ws, next_seq)
            except Exception:
                logger.exception("Ошибка обработки сообщения бота Hermes")


async def _run_forever() -> None:
    backoff = 2
    while True:
        if not (mattermost_service.is_configured() and settings_store.is_hermes_chat_enabled()):
            await asyncio.sleep(30)
            continue
        try:
            await _run_once()
            backoff = 2  # чистое завершение — сбрасываем задержку
        except Exception as exc:
            logger.warning("Hermes bot WebSocket оборван: %s — переподключение через %ss",
                           type(exc).__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def _acquire_singleton_lock() -> bool:
    """Захватить межпроцессную блокировку, чтобы слушатель был единственным.

    Возвращает True, если этот процесс стал владельцем слушателя.
    """
    global _lock_handle
    import fcntl

    lock_path = os.getenv("HERMES_BOT_LOCK_PATH")
    if not lock_path:
        data_dir = "/data" if os.path.isdir("/data") and os.access("/data", os.W_OK) else "/tmp"
        lock_path = os.path.join(data_dir, "hermes_bot_ws.lock")
    try:
        fh = open(lock_path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle = fh  # удерживаем дескриптор на всё время жизни процесса
        return True
    except (OSError, BlockingIOError):
        # Блокировку уже держит другой воркер — этот процесс слушатель не запускает.
        return False


def start_bot_listener() -> bool:
    """Запустить фоновый слушатель сообщений бота (в одном процессе)."""
    global _started
    if _started:
        return True
    if not settings_store.is_hermes_chat_enabled():
        logger.info("Чат-режим Hermes выключен — слушатель сообщений не запущен")
        return False
    if not mattermost_service.is_configured():
        logger.info("Mattermost bot не настроен — слушатель сообщений не запущен")
        return False
    if not _acquire_singleton_lock():
        logger.info("Слушатель сообщений Hermes уже запущен в другом воркере — пропускаем")
        return False

    def _thread_main():
        try:
            asyncio.run(_run_forever())
        except Exception:
            logger.exception("Слушатель сообщений Hermes аварийно остановлен")

    t = threading.Thread(target=_thread_main, name="hermes-bot-ws", daemon=True)
    t.start()
    _started = True
    logger.info("Слушатель сообщений бота Hermes запущен")
    return True
