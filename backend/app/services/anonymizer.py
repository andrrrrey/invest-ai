"""
Обезличивание данных для отправки во внешний ИИ.

Перед каждой отправкой в ИИ чувствительные данные (названия проектов, ФИО,
коды МВЗ, контакты) заменяются на обезличенные метки, а в ответе возвращаются
обратно. Это детерминированная и **обратимая** подмена: одно и то же значение
всегда получает одну и ту же метку в пределах вызова.

Обезличивание встраивается в единую точку общения с ИИ
(``ai_service._chat``), поэтому работает одинаково во всех сценариях.

Финансовые суммы по умолчанию СОХРАНЯЮТСЯ — они нужны для аналитики.
Опциональное округление сумм включается флагом ``anonymize_round_amounts``.

Основные функции:
  - ``anonymize(text, extra_terms=None)`` -> ``(masked_text, mapping)``
  - ``deanonymize(text, mapping)`` -> ``text``
  - ``collect_project_terms(project)`` -> dict — вытащить чувствительные
    значения из словаря проекта (для переиспользования в MCP-инструментах).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Порядок категорий влияет только на человекочитаемость меток.
CATEGORY_PREFIX = {
    "project": "PROJECT",
    "person": "PERSON",
    "mvz": "MVZ",
    "contact": "CONTACT",
    "org": "ORG",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Российские номера в распространённых форматах: +7 / 8, со скобками/дефисами/пробелами.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
# Именованные сущности в проекте почти всегда обёрнуты в «ёлочки»
# (например «{project_name}») — это надёжный сигнал в этом кодовом базисе.
_QUOTED_RE = re.compile(r"«([^»]+)»")
# Похоже на метку-плейсхолдер (чтобы не обезличивать её повторно).
_PLACEHOLDER_RE = re.compile(r"^\[[A-Z]+_\d+\]$")


def _register(
    original: str,
    category: str,
    mapping: Dict[str, str],
    seen: Dict[str, str],
    counters: Dict[str, int],
) -> str:
    """Вернуть метку для значения, создав её при первом появлении."""
    if original in seen:
        return seen[original]
    prefix = CATEGORY_PREFIX.get(category, "TERM")
    counters[category] = counters.get(category, 0) + 1
    placeholder = f"[{prefix}_{counters[category]}]"
    mapping[placeholder] = original
    seen[original] = placeholder
    return placeholder


def anonymize(
    text: str,
    extra_terms: Optional[Dict[str, List[str]]] = None,
) -> Tuple[str, Dict[str, str]]:
    """Заменить чувствительные данные на метки.

    :param text: исходный текст промпта.
    :param extra_terms: явно известные чувствительные значения по категориям,
        например ``{"project": [...], "person": [...], "mvz": [...]}``.
        Используется, когда вызывающий код знает структуру данных
        (названия, ФИО, коды МВЗ), которые нельзя надёжно распознать по тексту.
    :returns: кортеж ``(обезличенный_текст, mapping)``, где ``mapping`` —
        словарь ``метка -> исходное_значение`` для обратного восстановления.
    """
    if not text:
        return text, {}

    mapping: Dict[str, str] = {}
    seen: Dict[str, str] = {}
    counters: Dict[str, int] = {}

    # 1) Явно переданные термины — сначала самые длинные, чтобы более длинные
    #    вхождения (напр. полное ФИО) не разбивались более короткими.
    if extra_terms:
        items: List[Tuple[str, str]] = []
        for category, terms in extra_terms.items():
            for term in terms or []:
                if isinstance(term, str) and term.strip():
                    items.append((term.strip(), category))
        items.sort(key=lambda x: len(x[0]), reverse=True)
        for term, category in items:
            if term not in text:
                continue
            placeholder = _register(term, category, mapping, seen, counters)
            text = text.replace(term, placeholder)

    # 2) Контакты: email и телефоны.
    text = _EMAIL_RE.sub(
        lambda m: _register(m.group(0), "contact", mapping, seen, counters), text
    )
    text = _PHONE_RE.sub(
        lambda m: _register(m.group(0), "contact", mapping, seen, counters), text
    )

    # 3) Именованные сущности в «ёлочках» — маскируем содержимое, сохраняя кавычки.
    def _repl_quoted(m: "re.Match[str]") -> str:
        inner = m.group(1)
        # Не трогаем уже подставленную метку, напр. «[PROJECT_1]».
        if _PLACEHOLDER_RE.match(inner):
            return m.group(0)
        placeholder = _register(inner, "project", mapping, seen, counters)
        return f"«{placeholder}»"

    text = _QUOTED_RE.sub(_repl_quoted, text)

    return text, mapping


def deanonymize(text: str, mapping: Dict[str, str]) -> str:
    """Восстановить исходные значения из меток.

    Устойчиво к тому, что модель могла переставить метки местами: замена идёт
    по точному вхождению токена ``[CATEGORY_N]``. Закрывающая скобка в метке
    исключает коллизии вида ``[PROJECT_1]`` внутри ``[PROJECT_10]``.
    """
    if not text or not mapping:
        return text
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def collect_project_terms(project: dict) -> Dict[str, List[str]]:
    """Собрать чувствительные значения из словаря проекта.

    Переиспользуется вызывающим кодом (AI-сервис, позже — MCP-инструменты),
    чтобы передать в ``anonymize`` термины, которые нельзя надёжно распознать
    по свободному тексту: названия, ФИО участников/куратора, коды МВЗ.
    """
    terms: Dict[str, List[str]] = {
        "project": [],
        "person": [],
        "mvz": [],
        "contact": [],
        "org": [],
    }
    if not isinstance(project, dict):
        return terms

    def _add(category: str, value) -> None:
        if isinstance(value, str) and value.strip():
            v = value.strip()
            if v not in terms[category]:
                terms[category].append(v)

    _add("project", project.get("name"))
    _add("org", project.get("business_unit"))
    _add("person", project.get("owner"))

    # Смарт-контракт: куратор и команда.
    scd = project.get("smart_contract_data")
    if isinstance(scd, dict):
        _add("person", scd.get("curator"))
        for member in scd.get("team") or []:
            if isinstance(member, dict):
                _add("person", member.get("name"))

    # Коды МВЗ — как в financial_model, так и на верхнем уровне.
    for source in (project.get("financial_model"), project):
        if isinstance(source, dict):
            for key in ("op_mvz_main", "op_mvz_sub1", "op_mvz_sub2"):
                _add("mvz", source.get(key))

    return terms
