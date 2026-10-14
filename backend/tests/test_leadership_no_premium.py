"""Пункт 4 КП: лидерский контракт без премии (только фикс)."""

from app.services.export_pdf import _render_smart_contract_detail


def test_pdf_renders_fixed_only_leadership_contract():
    html = _render_smart_contract_detail({
        "id": 1, "name": "Только фикс", "status": "draft", "project_type": "smart_contract",
        "smart_contract_data": {
            "scType": "leadership", "fixedSalaryMonthly": 150000, "variableTotal": 0,
            "leadershipTotals": {"numMonths": 6, "totalSalary": 900000, "totalBonus": 0, "grand": 900000},
            "milestones": [{"name": "Этап", "deadline": "2026-12-31", "rewardRub": 0}],
        },
    })
    assert "без премии (только фикс)" in html
    assert "900,000" in html
