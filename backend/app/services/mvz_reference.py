"""
Справочник МВЗ (круги → подкруги → подкруги 2).

Структура МВЗ — каскадный справочник: главный круг (например, «3 | R&D»)
содержит подкруги первого уровня («3.1 | New Business»), а те — подкруги
второго уровня («3.1.1 | New Business GEN»).

Справочник хранится в настройках (settings_store) и редактируется
финансовым директором в разделе «Настройки → Справочник МВЗ».
Эталонный набор (DEFAULT_MVZ) используется, пока справочник не изменён
в настройках, поэтому система работает «из коробки».
"""

from typing import Any

# ── Эталонный справочник ───────────────────────────────────────────
# main_circles: [{id, name}]
# sub1: {main_id: [{id, name}]}
# sub2: {sub1_id: [{id, name}]}

DEFAULT_MVZ: dict[str, Any] = {
    "main_circles": [
        {"id": "1", "name": "PARTNERS"},
        {"id": "100", "name": "Sales"},
        {"id": "1000", "name": "Marketing"},
        {"id": "1100", "name": "Board of director"},
        {"id": "1400", "name": "Relations"},
        {"id": "2", "name": "Customer Support"},
        {"id": "3", "name": "R&D"},
        {"id": "400", "name": "Otherside"},
        {"id": "5", "name": "G&A"},
        {"id": "7", "name": "COGS"},
        {"id": "700", "name": "Clients"},
        {"id": "800", "name": "OPS"},
    ],
    "sub1": {
        "1": [{"id": "1.1", "name": "PARTNERS"}],
        "100": [
            {"id": "110", "name": "Sales"},
            {"id": "140", "name": "KAM"},
            {"id": "150", "name": "New Logos"},
            {"id": "160", "name": "Inbound"},
            {"id": "180", "name": "Sales OPS"},
        ],
        "1000": [
            {"id": "1010", "name": "Marketing"},
            {"id": "1020", "name": "Events"},
            {"id": "1030", "name": "Content"},
            {"id": "1040", "name": "Sites"},
            {"id": "1060", "name": "Креативный маркетинг"},
            {"id": "1070", "name": "Acquisition"},
            {"id": "1090", "name": "PM"},
        ],
        "1100": [{"id": "1110", "name": "Board of director"}],
        "1400": [{"id": "1410", "name": "Relations"}],
        "2": [{"id": "2.1", "name": "Custom technical support"}],
        "3": [
            {"id": "3.1", "name": "New Business"},
            {"id": "3.2", "name": "Право (судопроизводство)"},
            {"id": "3.3", "name": "eJ. КАД/MA"},
            {"id": "3.4", "name": "eJ. ПК САД (САС)"},
            {"id": "3.5", "name": "Право (Редактор)"},
            {"id": "3.8", "name": "CB. Discovery Право (дела)"},
            {"id": "3.9", "name": "CB. Discovery(данные)"},
            {"id": "3.10", "name": "CB. API. Tech"},
            {"id": "3.11", "name": "CB. CbForce"},
            {"id": "3.12", "name": "CB. Аркада"},
            {"id": "3.13", "name": "CB. Авангард"},
            {"id": "3.15", "name": "C1. Discovery Право (департамент)"},
            {"id": "3.16", "name": "C1. OPS + Arch"},
            {"id": "3.17", "name": "C1. Core Delivery TI"},
            {"id": "3.18", "name": "C1. Team.Two (T2)"},
            {"id": "3.19", "name": "C1. Core Discovery"},
            {"id": "3.20", "name": "C1. CustDev TI"},
            {"id": "3.22", "name": "Caselook"},
            {"id": "3.23", "name": "CL. Discovery (инициативы)"},
            {"id": "3.24", "name": "CL. Discovery (практика)"},
            {"id": "3.25", "name": "Doc.one"},
            {"id": "3.26", "name": "Bot.one"},
            {"id": "3.27", "name": "D1. Discovery(договоры)"},
            {"id": "3.29", "name": "CB. Право (Картотека)"},
            {"id": "3.30", "name": "D&D Process"},
            {"id": "3.31", "name": "Discovery AI"},
            {"id": "3.40", "name": "eJ. САС Support"},
        ],
        "400": [{"id": "420", "name": "Otherside"}],
        "5": [
            {"id": "5.1", "name": "C&B"},
            {"id": "5.2", "name": "Employee Experience"},
            {"id": "5.3", "name": "Recruitment"},
            {"id": "5.5", "name": "Кибербезопасность"},
        ],
        "7": [
            {"id": "7.1", "name": "DevOps"},
            {"id": "7.2", "name": "DevSup"},
        ],
        "700": [
            {"id": "720", "name": "Support"},
            {"id": "730", "name": "Academy"},
            {"id": "740", "name": "Clients GEN"},
            {"id": "750", "name": "Tutors"},
            {"id": "760", "name": "VIP поддержка"},
        ],
        "800": [
            {"id": "810", "name": "Finance"},
            {"id": "8110", "name": "Docs"},
            {"id": "820", "name": "Legal"},
            {"id": "830", "name": "Information systems"},
            {"id": "840", "name": "Infrastucture & IT"},
            {"id": "850", "name": "A&D"},
            {"id": "860", "name": "Offices & Services"},
            {"id": "870", "name": "KDP"},
            {"id": "890", "name": "OPS"},
        ],
    },
    "sub2": {
        "1.1": [{"id": "1.1.1", "name": "PARTNERS GEN"}],
        "110": [{"id": "111", "name": "Sales GEN"}],
        "140": [
            {"id": "142", "name": "KAM ENT Unit 1"},
            {"id": "143", "name": "KAM SMALL Unit 1"},
            {"id": "144", "name": "KAM ENT Unit 2"},
            {"id": "145", "name": "Experts"},
            {"id": "146", "name": "KYC"},
        ],
        "150": [
            {"id": "151", "name": "New logos Performers 1"},
            {"id": "152", "name": "New logos Performers 2"},
            {"id": "153", "name": "New logos Researchers 1"},
            {"id": "154", "name": "New logos Performers 3"},
            {"id": "155", "name": "New logos Performers 4"},
            {"id": "156", "name": "New logos Researchers 2"},
        ],
        "160": [{"id": "161", "name": "Inbound GEN"}],
        "180": [{"id": "181", "name": "Sales OPS GEN"}],
        "1010": [{"id": "1014", "name": "Marketing GEN"}],
        "1020": [{"id": "1021", "name": "Events GEN"}],
        "1030": [{"id": "1031", "name": "Content GEN"}],
        "1040": [{"id": "1041", "name": "Sites GEN"}],
        "1060": [{"id": "1061", "name": "Креативный маркетинг GEN"}],
        "1070": [{"id": "1071", "name": "Acquisition GEN"}],
        "1090": [{"id": "1091", "name": "PM GEN"}],
        "1110": [{"id": "1111", "name": "Board of director"}],
        "1410": [{"id": "1411", "name": "Relations GEN"}],
        "2.1": [{"id": "2.1.1", "name": "Custom technical support GEN"}],
        "3.1": [{"id": "3.1.1", "name": "New Business GEN"}],
        "3.2": [{"id": "3.2.1", "name": "Право (судопроизводство) GEN"}],
        "3.3": [{"id": "3.3.1", "name": "eJ. КАД/MA GEN"}],
        "3.4": [{"id": "3.4.1", "name": "eJ. ПК САД (САС) GEN"}],
        "3.5": [{"id": "3.5.1", "name": "eJ. САС Support GEN"}],
        "3.8": [{"id": "3.8.1", "name": "CB. Discovery Право (дела) GEN"}],
        "3.9": [{"id": "3.9.1", "name": "CB. Discovery(данные) GEN"}],
        "3.10": [{"id": "3.10.1", "name": "CB. API. Tech GEN"}],
        "3.11": [{"id": "3.11.1", "name": "CB. CbForce GEN"}],
        "3.12": [{"id": "3.12.1", "name": "CB. Аркада GEN"}],
        "3.13": [{"id": "3.13.1", "name": "CB. Авангард GEN"}],
        "3.15": [{"id": "3.15.1", "name": "C1. Discovery Право (департамент) GEN"}],
        "3.16": [{"id": "3.16.1", "name": "C1. OPS + Arch GEN"}],
        "3.17": [{"id": "3.17.1", "name": "C1. Core Delivery TI GEN"}],
        "3.18": [{"id": "3.18.1", "name": "C1. Team.Two (T2) GEN"}],
        "3.19": [{"id": "3.19.1", "name": "C1. Core Discovery GEN"}],
        "3.20": [{"id": "3.20.1", "name": "C1. CustDev TI GEN"}],
        "3.22": [{"id": "3.22.1", "name": "Caselook GEN"}],
        "3.23": [{"id": "3.23.1", "name": "CL. Discovery (инициативы) GEN"}],
        "3.24": [{"id": "3.24.1", "name": "CL. Discovery (практика) GEN"}],
        "3.25": [{"id": "3.25.1", "name": "Doc.one GEN"}],
        "3.26": [{"id": "3.26.1", "name": "Bot.one GEN"}],
        "3.27": [{"id": "3.27.1", "name": "D1. Discovery(договоры) GEN"}],
        "3.29": [{"id": "3.29.1", "name": "CB. Право (Картотека) GEN"}],
        "3.30": [{"id": "3.30.1", "name": "D&D Process GEN"}],
        "3.31": [{"id": "3.31.1", "name": "Discovery AI GEN"}],
        "3.40": [{"id": "3.40.1", "name": "eJ. САС Support GEN"}],
        "420": [{"id": "421", "name": "Otherside"}],
        "5.1": [{"id": "5.1.1", "name": "C&B GEN"}],
        "5.2": [{"id": "5.2.1", "name": "Employee Experience GEN"}],
        "5.3": [{"id": "5.3.1", "name": "Recruitment GEN"}],
        "5.5": [{"id": "5.5.1", "name": "Кибербезопасность GEN"}],
        "7.1": [{"id": "7.1.1", "name": "DevOps GEN"}],
        "7.2": [{"id": "7.2.1", "name": "DevSup GEN"}],
        "720": [
            {"id": "721", "name": "Support Casebook & Caselook"},
            {"id": "722", "name": "Support API Casebook"},
            {"id": "723", "name": "Support Work"},
            {"id": "724", "name": "Support GEN"},
            {"id": "725", "name": "Support КАД"},
        ],
        "730": [{"id": "731", "name": "Academy GEN"}],
        "740": [{"id": "741", "name": "Clients GEN"}],
        "750": [{"id": "751", "name": "Tutors GEN"}],
        "760": [{"id": "761", "name": "VIP поддержка GEN"}],
        "810": [
            {"id": "811", "name": "Financial reporting & budgeting"},
            {"id": "812", "name": "Accounting"},
            {"id": "814", "name": "Finance GEN"},
        ],
        "8110": [
            {"id": "8111", "name": "Docs GEN"},
            {"id": "8112", "name": "K.Docs"},
            {"id": "8113", "name": "W.Docs"},
            {"id": "8114", "name": "Service"},
        ],
        "820": [{"id": "821", "name": "Legal GEN"}],
        "830": [{"id": "831", "name": "Information systems GEN"}],
        "840": [{"id": "841", "name": "Infrastucture & IT GEN"}],
        "850": [{"id": "851", "name": "A&D GEN"}],
        "860": [{"id": "861", "name": "Offices & Services GEN"}],
        "870": [{"id": "871", "name": "KDP"}],
        "890": [{"id": "891", "name": "OPS GEN"}],
    },
}


def _valid_rows(rows: Any) -> list[dict[str, str]]:
    """Привести список элементов справочника к корректному виду."""
    out: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        if not rid:
            continue
        out.append({"id": rid, "name": name or rid})
    return out


def validate_mvz(data: Any) -> dict[str, Any]:
    """Проверить и нормализовать присланный справочник МВЗ.

    Возвращает нормализованную структуру. Бросает ``ValueError`` с
    человекочитаемым сообщением, если структура некорректна.
    """
    if not isinstance(data, dict):
        raise ValueError("Справочник МВЗ должен быть объектом")

    main = _valid_rows(data.get("main_circles"))
    if not main:
        raise ValueError("Не указан ни одного главного круга МВЗ")

    sub1_raw = data.get("sub1") or {}
    sub2_raw = data.get("sub2") or {}
    if not isinstance(sub1_raw, dict) or not isinstance(sub2_raw, dict):
        raise ValueError("Подкруги МВЗ должны быть объектами")

    main_ids = {row["id"] for row in main}
    sub1: dict[str, list[dict[str, str]]] = {}
    for key, rows in sub1_raw.items():
        key = str(key).strip()
        if key not in main_ids:
            continue  # подкруг без родителя — игнорируем
        normalized = _valid_rows(rows)
        if normalized:
            sub1[key] = normalized

    sub1_ids = {row["id"] for rows in sub1.values() for row in rows}
    sub2: dict[str, list[dict[str, str]]] = {}
    for key, rows in sub2_raw.items():
        key = str(key).strip()
        if key not in sub1_ids:
            continue
        normalized = _valid_rows(rows)
        if normalized:
            sub2[key] = normalized

    return {"main_circles": main, "sub1": sub1, "sub2": sub2}
