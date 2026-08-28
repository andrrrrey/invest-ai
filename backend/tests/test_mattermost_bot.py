"""Тесты разбора входящих сообщений WebSocket-слушателя бота Hermes."""

import json

from app.services.mattermost_bot_service import parse_incoming

BOT_ID = "botuser123"
BOT_NAME = "hermes"


def _event(message, *, channel_type="D", user_id="u1", mentions=None,
           post_type="", props=None, post_id="p1", root_id=""):
    post = {
        "id": post_id,
        "channel_id": "chan1",
        "user_id": user_id,
        "message": message,
        "type": post_type,
        "root_id": root_id,
        "props": props or {},
    }
    data = {"post": json.dumps(post), "channel_type": channel_type, "sender_name": "@ivan"}
    if mentions is not None:
        data["mentions"] = json.dumps(mentions)
    return {"event": "posted", "data": data}


def test_direct_message_is_handled():
    res = parse_incoming(_event("статус проекта X"), BOT_ID, BOT_NAME)
    assert res is not None
    assert res["text"] == "статус проекта X"
    assert res["channel_id"] == "chan1"
    assert res["root_id"] == "p1"          # not in a thread → reply to the post


def test_bot_own_message_ignored():
    assert parse_incoming(_event("привет", user_id=BOT_ID), BOT_ID, BOT_NAME) is None


def test_message_from_other_bot_ignored():
    ev = _event("я бот", props={"from_bot": "true"})
    assert parse_incoming(ev, BOT_ID, BOT_NAME) is None


def test_system_message_ignored():
    ev = _event("joined the channel", post_type="system_join_channel")
    assert parse_incoming(ev, BOT_ID, BOT_NAME) is None


def test_empty_message_ignored():
    assert parse_incoming(_event("   "), BOT_ID, BOT_NAME) is None


def test_channel_message_without_mention_ignored():
    ev = _event("просто болтаем", channel_type="O")
    assert parse_incoming(ev, BOT_ID, BOT_NAME) is None


def test_channel_mention_by_id_is_handled_and_stripped():
    ev = _event("@hermes какие заявки ждут согласования", channel_type="O", mentions=[BOT_ID])
    res = parse_incoming(ev, BOT_ID, BOT_NAME)
    assert res is not None
    assert res["text"] == "какие заявки ждут согласования"


def test_channel_mention_by_text_is_handled():
    ev = _event("@hermes сводка", channel_type="O")  # mentions отсутствует
    res = parse_incoming(ev, BOT_ID, BOT_NAME)
    assert res is not None
    assert res["text"] == "сводка"


def test_reply_goes_to_thread_root():
    ev = _event("вопрос в треде", root_id="root99")
    res = parse_incoming(ev, BOT_ID, BOT_NAME)
    assert res["root_id"] == "root99"


def test_non_posted_event_ignored():
    assert parse_incoming({"event": "typing", "data": {}}, BOT_ID, BOT_NAME) is None
