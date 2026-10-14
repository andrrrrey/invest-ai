"""Пункт 1 КП: раздельные реестры смарт- и лидерских контрактов."""

from _helpers import client, mk_user, auth, mk_contract


def test_list_filters_by_sc_type():
    cfo = mk_user("cfo")
    smart_id = mk_contract(cfo, "smart")
    lead_id = mk_contract(cfo, "leadership")

    r = client.get("/api/v1/projects/?project_type=smart_contract&sc_type=smart", headers=auth(cfo))
    ids = {p["id"] for p in r.json()}
    assert smart_id in ids and lead_id not in ids

    r = client.get("/api/v1/projects/?project_type=smart_contract&sc_type=leadership", headers=auth(cfo))
    ids = {p["id"] for p in r.json()}
    assert lead_id in ids and smart_id not in ids

    # Без sc_type — оба вида.
    r = client.get("/api/v1/projects/?project_type=smart_contract", headers=auth(cfo))
    ids = {p["id"] for p in r.json()}
    assert {smart_id, lead_id} <= ids


def test_stats_scoped_by_sc_type():
    owner = mk_user("owner")
    mk_contract(owner, "leadership")
    mk_contract(owner, "leadership")
    mk_contract(owner, "smart")
    r = client.get("/api/v1/stats/?project_type=smart_contract&sc_type=leadership", headers=auth(owner))
    assert r.json()["total"] == 2
    r = client.get("/api/v1/stats/?project_type=smart_contract&sc_type=smart", headers=auth(owner))
    assert r.json()["total"] == 1


def test_label_for_distinguishes_contracts():
    from app.services import links
    from _helpers import get_project
    owner = mk_user("owner")
    assert links.label_for(get_project(mk_contract(owner, "leadership"))) == "Лидерский контракт"
    assert links.label_for(get_project(mk_contract(owner, "smart"))) == "Смарт-контракт"
    assert links.project_path("smart_contract", 5) == "/smart-contract?id=5"
