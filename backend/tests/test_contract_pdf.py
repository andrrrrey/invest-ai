"""Пункт 12 КП: PDF по отдельному контракту."""

from _helpers import client, mk_user, auth, mk_contract
from app.services.export_pdf import _render_smart_contract_detail


def test_contract_pdf_download():
    owner = mk_user("owner")
    pid = mk_contract(owner, "smart", "draft", navRate=12.5, navRateDate="2026-10-14", customerName="Заказчиков",
                      milestones=[{"name": "Пилот", "deadline": "2026-12-15", "rewardRub": 600000, "coins": 48000,
                                   "criteria": "Деплой ≤ 10 мин"}])
    r = client.get(f"/api/v1/projects/{pid}/pdf", headers=auth(owner))
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    other = mk_user("owner")
    assert client.get(f"/api/v1/projects/{pid}/pdf", headers=auth(other)).status_code == 403


def test_renderer_uses_wizard_keys_and_sections():
    html = _render_smart_contract_detail({
        "name": "Контракт", "status": "pending_approval", "owner": "Лидеров Пётр",
        "smart_contract_data": {
            "scType": "smart", "navRate": 12.5, "navRateDate": "2026-10-14", "customerName": "Заказчиков Иван",
            "milestones": [{"name": "Пилот CI/CD", "deadline": "2026-12-15", "rewardRub": 600000, "coins": 48000}],
        },
        "approval_route": {"steps": [{"role_label": "C&B", "assignee": "Кулеева", "status": "approved",
                                      "sent_at": "2026-10-14T04:26:00", "decided_at": "2026-10-14T05:00:00",
                                      "comment": "ок"}]},
        "history": [{"ts": "2026-10-14T05:00:00", "kind": "change", "title": "Изменено: Название", "by": "X",
                     "old": "А", "new": "Б"}],
    })
    assert "Пилот CI/CD" in html and "15.12.2026" in html
    assert "Заказчиков Иван" in html and "на 14.10.2026" in html
    assert "6. Согласование" in html and "Кулеева" in html
    assert "7. История" in html and "А → Б" in html
