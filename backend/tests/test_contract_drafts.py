"""Пункт 2 КП: черновики контрактов."""

from _helpers import client, mk_user, auth, get_project, setup_route_roles


def _payload(**over):
    p = {
        "project_type": "smart_contract",
        "name": "Черновик",
        "status": "draft",
        "smart_contract_data": {"scType": "smart", "wizardStep": 3, "milestones": []},
    }
    p.update(over)
    return p


def test_create_draft_and_update_keeps_status():
    owner = mk_user("owner")
    r = client.post("/api/v1/projects/", headers=auth(owner), json=_payload())
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "draft"

    # PUT не может перевести контракт в другой статус в обход согласования.
    r = client.put(f"/api/v1/projects/{pid}", headers=auth(owner),
                   json=_payload(name="Обновлён", status="approved"))
    assert r.status_code == 200, r.text
    p = get_project(pid)
    assert p.status == "draft"
    assert p.name == "Обновлён"
    assert p.smart_contract_data["wizardStep"] == 3


def test_owner_can_edit_rework_but_not_pending_contract():
    setup_route_roles()
    owner = mk_user("owner")
    customer = mk_user("manager")
    pid = client.post("/api/v1/projects/", headers=auth(owner), json=_payload(
        smart_contract_data={"scType": "smart", "customerUserId": customer})).json()["id"]
    r = client.patch(f"/api/v1/projects/{pid}/status", headers=auth(owner), json={"status": "pending_approval"})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/v1/projects/{pid}", headers=auth(owner), json=_payload(name="X"))
    assert r.status_code == 403
