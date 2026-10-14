"""Пункт 6 КП: курс Coin на дату."""

import datetime as dt

from _helpers import client, mk_user, auth
from app.database import SessionLocal
from app.services import coin_rate_service


def _set(uid, date, rate):
    return client.post("/api/v1/coin-rates", headers=auth(uid),
                       json={"effective_date": date, "rate": rate, "comment": "квартал"})


def test_rate_on_date_uses_latest_effective_record():
    cfo = mk_user("cfo")
    assert _set(cfo, "2020-01-01", 9.0).status_code == 201
    assert _set(cfo, "2020-04-01", 11.0).status_code == 201
    s = SessionLocal()
    try:
        assert coin_rate_service.rate_on(s, dt.date(2020, 3, 31)) == 9.0
        assert coin_rate_service.rate_on(s, dt.date(2020, 4, 1)) == 11.0
        assert coin_rate_service.rate_on(s, dt.date(2020, 6, 15)) == 11.0
    finally:
        s.close()
    r = client.get("/api/v1/coin-rates/effective?date=2020-02-10", headers=auth(cfo)).json()
    assert r["rate"] == 9.0 and r["effective_date"] == "2020-01-01"
    # Повторная установка на ту же дату заменяет курс.
    assert _set(cfo, "2020-01-01", 9.5).status_code == 201
    r = client.get("/api/v1/coin-rates/effective?date=2020-02-10", headers=auth(cfo)).json()
    assert r["rate"] == 9.5


def test_only_cfo_and_treasurer_manage_rates():
    cfo = mk_user("cfo")
    manager = mk_user("manager")
    treasurer = mk_user("owner")
    assert _set(manager, "2019-01-01", 8.0).status_code == 403
    client.put("/api/v1/approval-roles", headers=auth(cfo), json={"treasurer": treasurer})
    assert _set(treasurer, "2019-01-01", 8.0).status_code == 201
    listing = client.get("/api/v1/coin-rates", headers=auth(treasurer)).json()
    assert listing["can_manage"] is True
    assert client.get("/api/v1/coin-rates", headers=auth(manager)).json()["can_manage"] is False


def test_contract_gets_rate_of_creation_date():
    cfo = mk_user("cfo")
    today = dt.date.today().isoformat()
    _set(cfo, today, 20.0)
    r = client.post("/api/v1/projects/", headers=auth(cfo), json={
        "project_type": "smart_contract", "name": "Курс", "status": "draft",
        "smart_contract_data": {"scType": "smart", "navRate": 10.1,
                                "milestones": [{"name": "Э", "rewardRub": 1000, "coins": 99}],
                                "team": [{"name": "А", "coins": 99}]},
    })
    scd = r.json()["smart_contract_data"]
    assert scd["navRate"] == 20.0
    assert scd["navRateDate"] == today
    assert scd["milestones"][0]["coins"] == 50
    assert scd["team"][0]["coins"] == 50


def test_recalc_keeps_team_proportions():
    scd = coin_rate_service.recalc_contract_coins(
        {"scType": "smart", "milestones": [{"rewardRub": 1000, "coins": 100}],
         "team": [{"name": "A", "coins": 60}, {"name": "B", "coins": 40}]}, 20.0)
    assert [t["coins"] for t in scd["team"]] == [30, 20]
