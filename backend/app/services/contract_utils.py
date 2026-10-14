"""Общие хелперы для смарт- и лидерских контрактов.

Контракты хранятся в таблице ``projects`` (``project_type='smart_contract'``),
а их вид — смарт-контракт с вознаграждением в Coin или лидерский контракт —
лежит в ``smart_contract_data.scType``.
"""

from __future__ import annotations

SC_TYPES = ("smart", "leadership")

SC_TYPE_LABELS = {
    "smart": "Смарт-контракт",
    "leadership": "Лидерский контракт",
}


def sc_type_of(project) -> str:
    """Вид контракта: ``smart`` (по умолчанию) или ``leadership``."""
    scd = getattr(project, "smart_contract_data", None) or {}
    return "leadership" if scd.get("scType") == "leadership" else "smart"


def is_contract(project) -> bool:
    return (getattr(project, "project_type", None) or "") == "smart_contract"


def contract_label(project) -> str:
    return SC_TYPE_LABELS[sc_type_of(project)]


def filter_by_sc_type(projects, sc_type: str | None):
    """Отфильтровать список контрактов по виду (``None`` — без фильтра)."""
    if sc_type not in SC_TYPES:
        return list(projects)
    return [p for p in projects if sc_type_of(p) == sc_type]
