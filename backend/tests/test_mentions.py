"""Пункт 8 КП: теги @ в комментариях и уведомления."""

from _helpers import client, mk_user, auth, mk_contract
from app.database import SessionLocal
from app.models.notification import Notification
from app.services import mattermost_service, mention_service
import random

_ABC = "абвгдежзиклмнопрстуфхцчшэюя"


def _surname(base):
    # Уникальная фамилия: тестовая БД общая для всей сессии.
    return base + "".join(random.choice(_ABC) for _ in range(5))


def test_parse_mentions_variants():
    k, h, p = _surname("Кулеева"), _surname("Хагуш"), _surname("Петров")
    a = mk_user("manager", full_name=f"{k} Маргарита")
    b = mk_user("owner", full_name=f"{h} Лонда")
    c1 = mk_user("owner", full_name=f"{p} Алексей")
    c2 = mk_user("owner", full_name=f"{p} Борис")
    s = SessionLocal()
    try:
        ids = lambda t: {u.id for u in mention_service.parse_mentions(s, t)}
        assert ids(f"@{k} посмотри") == {a}
        assert ids(f"Коллеги, @{h.lower()} лонда и #{k} — нужно решение") == {a, b}
        assert ids(f"@{p} Борис проверь") == {c2}
        assert ids(f"@{p}, проверь") == {c1, c2}          # неоднозначно — оба
        assert ids(f"email user@{k}.ru") == set()          # не тег
        assert not mention_service.parse_mentions(s, f"@{k}", exclude_user_id=a)
    finally:
        s.close()


def test_comment_mention_notifies_with_deep_link(monkeypatch):
    sent = []
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: True)
    monkeypatch.setattr(mattermost_service, "post_to_email", lambda email, text, attachments=None: sent.append((email, text)) or True)
    author = mk_user("cfo")
    name = f"{_surname('Кувшинчикова')} Кристина"
    tagged = mk_user("owner", full_name=name)
    pid = mk_contract(author)
    r = client.post(f"/api/v1/projects/{pid}/comments", headers=auth(author),
                    json={"text": f"@{name} проверьте курс"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["mentions"] == [{"id": tagged, "full_name": name}]
    s = SessionLocal()
    try:
        n = s.query(Notification).filter_by(user_id=tagged, project_id=pid).one()
        assert n.link == f"/smart-contract?id={pid}#comment-{data['id']}"
        assert "упомянул" in n.title
    finally:
        s.close()
    assert len(sent) == 1 and "проверьте курс" in sent[0][1]
    listed = client.get(f"/api/v1/projects/{pid}/comments", headers=auth(author)).json()
    assert listed[0]["mentions"][0]["id"] == tagged


def test_mentioned_owner_can_open_card_and_reply(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    author = mk_user("owner")
    name = f"{_surname('Тегов')} Олег"
    tagged = mk_user("owner", full_name=name)
    pid = mk_contract(author)
    assert client.get(f"/api/v1/projects/{pid}", headers=auth(tagged)).status_code == 403
    client.post(f"/api/v1/projects/{pid}/comments", headers=auth(author), json={"text": f"@{name}, глянь"})
    assert client.get(f"/api/v1/projects/{pid}", headers=auth(tagged)).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/comments", headers=auth(tagged),
                       json={"text": "Посмотрел"}).status_code == 201
