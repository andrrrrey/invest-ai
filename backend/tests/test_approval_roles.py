"""Пункт 5 КП: роли согласующих (назначение в настройках)."""

from _helpers import client, mk_user, auth


def test_cfo_assigns_roles_and_user_sees_own_roles():
    cfo = mk_user("cfo")
    cb = mk_user("manager", full_name="Кулеева Маргарита")
    treasurer = mk_user("owner", full_name="Кувшинчикова Кристина")
    r = client.put("/api/v1/approval-roles", headers=auth(cfo), json={"cb": cb, "treasurer": treasurer})
    assert r.status_code == 200, r.text
    by_role = {x["role"]: x for x in r.json()}
    assert by_role["cb"]["full_name"] == "Кулеева Маргарита"
    assert by_role["treasurer"]["user_id"] == treasurer
    # Финдиректор без явного назначения — первый активный CFO.
    assert by_role["cfo"]["user_id"] is not None

    assert client.get("/api/v1/approval-roles/me", headers=auth(cb)).json()["roles"] == ["cb"]
    assert client.get("/api/v1/approval-roles/me", headers=auth(treasurer)).json()["roles"] == ["treasurer"]


def test_only_cfo_can_assign_and_unknown_role_rejected():
    manager = mk_user("manager")
    assert client.put("/api/v1/approval-roles", headers=auth(manager), json={"cb": manager}).status_code == 403
    cfo = mk_user("cfo")
    assert client.put("/api/v1/approval-roles", headers=auth(cfo), json={"boss": cfo}).status_code == 400
    assert client.put("/api/v1/approval-roles", headers=auth(cfo), json={"lawyer": 999999}).status_code == 400
