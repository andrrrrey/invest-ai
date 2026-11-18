"""Просмотр контракта ответственным/заказчиками/куратором, несколько
заказчиков, маршрут лидерского контракта, отчёт по этапу, «Фамилия Имя»."""

from _helpers import client, mk_user, auth, get_project, setup_route_roles
from app.services import mattermost_service
from app.services.names import surname_first


def _create(author, sc_type="smart", **extra):
    scd = {"scType": sc_type, "navRate": 10.0,
           "milestones": [{"name": "Этап", "rewardRub": 1000, "coins": 100}]}
    owner_user_id = extra.pop("owner_user_id", None)
    scd.update(extra)
    body = {"project_type": "smart_contract", "name": "Контракт", "status": "draft", "smart_contract_data": scd}
    if owner_user_id:
        body["owner_user_id"] = owner_user_id
    r = client.post("/api/v1/projects/", headers=auth(author), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _route(uid, pid):
    return client.get(f"/api/v1/projects/{pid}/route?route=contract", headers=auth(uid)).json()


def test_curator_customer_responsible_view_and_comment():
    author, leader, curator, c1, c2, stranger = (mk_user("owner") for _ in range(6))
    pid = _create(author, owner_user_id=leader, curatorUserId=curator, curator="Куратор",
                  customerUserIds=[c1, c2], customerUserId=c1)
    for uid in (leader, curator, c1, c2):
        assert client.get(f"/api/v1/projects/{pid}", headers=auth(uid)).status_code == 200
        ids = [p["id"] for p in client.get("/api/v1/projects/?project_type=smart_contract&sc_type=smart",
                                           headers=auth(uid)).json()]
        assert pid in ids
        r = client.post(f"/api/v1/projects/{pid}/comments", headers=auth(uid), json={"text": "Вопрос"})
        assert r.status_code == 201
        # Режим просмотра: редактировать и отправлять на согласование нельзя.
        assert client.put(f"/api/v1/projects/{pid}", headers=auth(uid),
                          json={"name": "Хак"}).status_code == 403
        assert client.patch(f"/api/v1/projects/{pid}/status", headers=auth(uid),
                            json={"status": "pending_approval"}).status_code == 403
    assert client.get(f"/api/v1/projects/{pid}", headers=auth(stranger)).status_code == 403
    assert client.put(f"/api/v1/projects/{pid}", headers=auth(author), json={"name": "Ок"}).status_code == 200


def test_multiple_customers_approve_in_turn(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    roles = setup_route_roles()
    author, c1, c2 = mk_user("owner"), mk_user("manager"), mk_user("manager")
    pid = _create(author, customerUserIds=[c1, c2], customerUserId=c1)
    assert client.patch(f"/api/v1/projects/{pid}/status", headers=auth(author),
                        json={"status": "pending_approval"}).status_code == 200
    steps = _route(author, pid)["steps"]
    assert [s["role"] for s in steps] == ["cb", "customer", "customer", "treasurer", "cfo"]
    assert [s["assignee_id"] for s in steps[1:3]] == [c1, c2]
    for uid, st in zip([roles["cb"], c1, c2, roles["treasurer"], roles["cfo"]], steps):
        r = client.post(f"/api/v1/projects/{pid}/route/steps/{st['id']}/decision",
                        headers=auth(uid), json={"decision": "approve"})
        assert r.status_code == 200, r.text
    assert get_project(pid).status == "approved"


def test_leadership_route_has_bonus_manager_not_treasurer(monkeypatch):
    monkeypatch.setattr(mattermost_service, "is_configured", lambda: False)
    setup_route_roles()
    author, customer = mk_user("owner"), mk_user("manager")
    pid = _create(author, "leadership", customerUserId=customer)
    preview = _route(author, pid)["steps"]
    assert [s["role"] for s in preview] == ["cb", "customer", "bonus_manager", "cfo"]
    assert preview[2]["role_label"] == "Менеджер по премии"
    assert client.patch(f"/api/v1/projects/{pid}/status", headers=auth(author),
                        json={"status": "pending_approval"}).status_code == 200
    assert [s["role"] for s in _route(author, pid)["steps"]] == ["cb", "customer", "bonus_manager", "cfo"]


def test_milestone_report():
    author, leader, curator = mk_user("owner"), mk_user("owner"), mk_user("owner")
    pid = _create(author, owner_user_id=leader, curatorUserId=curator)
    url = f"/api/v1/projects/{pid}/milestones/0/report"
    assert client.put(url, headers=auth(curator), json={"report": "x"}).status_code == 403
    r = client.put(url, headers=auth(leader), json={"report": "  Агент запущен  "})
    assert r.status_code == 200 and r.json()["report"] == "Агент запущен"
    ms = get_project(pid).smart_contract_data["milestones"][0]
    assert ms["report"] == "Агент запущен" and ms["reportBy"]
    assert client.put(url, headers=auth(leader), json={"report": ""}).status_code == 200
    assert "report" not in get_project(pid).smart_contract_data["milestones"][0]
    assert client.put(f"/api/v1/projects/{pid}/milestones/5/report", headers=auth(leader),
                      json={"report": "x"}).status_code == 404


def test_surname_first_and_directory():
    assert surname_first("Маргарита Кулеева") == "Кулеева Маргарита"
    assert surname_first("Кулеева Маргарита") == "Кулеева Маргарита"
    assert surname_first("Иван Иванович Иванов") == "Иванов Иван Иванович"
    assert surname_first("Иванов Иван Иванович") == "Иванов Иван Иванович"
    uid = mk_user("owner", full_name="Яна Аааева")
    rows = client.get("/api/v1/users/directory", headers=auth(uid)).json()
    me = next(r for r in rows if r["id"] == uid)
    assert me["display_name"] == "Аааева Яна" and me["full_name"] == "Яна Аааева"
    names = [r["display_name"].lower().replace("ё", "е") for r in rows]
    assert names == sorted(names)
