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
