"""Юнит-тесты обезличивания: обратимость, полнота, сохранение сумм."""

from app.services import anonymizer


def test_roundtrip_full_restore():
    text = "Проект «Секретный Атлас» ведёт Иван Петров, e-mail ivan@example.com"
    masked, mapping = anonymizer.anonymize(text, {"person": ["Иван Петров"]})

    # В обезличенном тексте нет исходных чувствительных значений.
    assert "Секретный Атлас" not in masked
    assert "Иван Петров" not in masked
    assert "ivan@example.com" not in masked

    # Восстановление возвращает исходный текст полностью.
    assert anonymizer.deanonymize(masked, mapping) == text


def test_amounts_are_preserved():
    text = "Бюджет проекта «Альфа»: 1 500 000 ₽, NPV 2 300 000 ₽"
    masked, _ = anonymizer.anonymize(text)
    assert "1 500 000 ₽" in masked
    assert "2 300 000 ₽" in masked


def test_phone_is_masked():
    text = "Свяжитесь: +7 (999) 123-45-67"
    masked, mapping = anonymizer.anonymize(text)
    assert "+7 (999) 123-45-67" not in masked
    assert anonymizer.deanonymize(masked, mapping) == text


def test_stable_numbering_and_dedup():
    text = "«Альфа» и снова «Альфа» и «Бета»"
    masked, mapping = anonymizer.anonymize(text)
    # Одно значение -> одна метка, использованная дважды.
    assert masked.count("[PROJECT_1]") == 2
    assert "[PROJECT_2]" in masked
    assert len(mapping) == 2


def test_json_instructions_not_broken():
    text = 'Верни JSON: {"name": "«Гамма»"}'
    masked, mapping = anonymizer.anonymize(text)
    # Скобки JSON не затронуты, roundtrip корректен.
    assert anonymizer.deanonymize(masked, mapping) == text


def test_disabled_when_no_terms_and_no_matches():
    text = "Суммарный NPV 5 000 000 ₽, средний IRR 18%."
    masked, mapping = anonymizer.anonymize(text)
    assert masked == text
    assert mapping == {}


def test_stateful_anonymizer_consistent_across_calls():
    az = anonymizer.Anonymizer()
    first = az.mask("Вопрос про «Альфа»")
    second = az.mask('{"name": "Альфа", "status": "draft"}', {"project": ["Альфа"]})
    # Одно значение -> одна и та же метка в разных вызовах.
    assert "[PROJECT_1]" in first
    assert "[PROJECT_1]" in second
    assert "Альфа" not in second
    # Восстановление работает по накопленному mapping.
    assert az.unmask("Ответ по [PROJECT_1]") == "Ответ по Альфа"


def test_short_numeric_terms_do_not_corrupt_other_numbers():
    """Регресс: короткий числовой код МВЗ не должен портить цифры внутри других
    чисел (id проекта, даты) — замена только по границам слова."""
    text = "Проект ID: 52, утверждён 2026-06-29, бюджет 500"
    masked, mapping = anonymizer.anonymize(text, {"mvz": ["5", "2"]})
    # Числа сохранены целиком.
    assert "52" in masked
    assert "2026-06-29" in masked
    assert "500" in masked
    # Отдельный токен «5»/«2» в этом тексте не встречается — маскировать нечего.
    assert masked == text


def test_standalone_numeric_term_is_masked_but_neighbors_not():
    text = "Код 5 и число 52"
    masked, mapping = anonymizer.anonymize(text, {"mvz": ["5"]})
    assert "52" in masked                 # не тронуто
    assert "Код 5 " not in masked         # отдельная «5» замаскирована
    assert anonymizer.deanonymize(masked, mapping) == text


def test_mask_obj_preserves_numeric_id():
    """Регресс: числовой код МВЗ не должен портить целочисленный id проекта."""
    az = anonymizer.Anonymizer()
    result = {
        "count": 1,
        "projects": [
            {"id": 12, "name": "Найм DBA-инженера", "business_unit": "WealthTech",
             "npv": 0.0, "irr": None},
        ],
    }
    terms = {"project": ["Найм DBA-инженера"], "org": ["WealthTech"], "mvz": ["12", "3"]}
    masked = az.mask_obj(result, terms)

    row = masked["projects"][0]
    # id остаётся валидным целым числом — агент сможет вызвать get_project(12).
    assert row["id"] == 12 and isinstance(row["id"], int)
    assert masked["count"] == 1
    assert row["npv"] == 0.0
    # Название и бизнес-юнит обезличены.
    assert row["name"] != "Найм DBA-инженера"
    assert row["business_unit"] != "WealthTech"
    # И восстанавливаются обратно.
    assert az.unmask(row["name"]) == "Найм DBA-инженера"


def test_collect_project_terms():
    project = {
        "name": "Секрет",
        "business_unit": "Финтех",
        "owner": "Сергей Иванов",
        "smart_contract_data": {"curator": "Пётр", "team": [{"name": "Анна"}]},
        "financial_model": {"op_mvz_main": "МВЗ-100", "op_mvz_sub1": "МВЗ-101"},
    }
    terms = anonymizer.collect_project_terms(project)
    assert "Секрет" in terms["project"]
    assert "Финтех" in terms["org"]
    assert "Пётр" in terms["person"] and "Анна" in terms["person"]
    assert "Сергей Иванов" in terms["person"]
    assert "МВЗ-100" in terms["mvz"] and "МВЗ-101" in terms["mvz"]
