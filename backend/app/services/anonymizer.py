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

# Ключи-идентификаторы и ссылки: их значения не маскируются, чтобы ИИ мог
# обращаться к инструментам по корректному id и давать рабочие ссылки на
# проекты (см. Anonymizer.mask_obj). Ссылка содержит только домен и числовой
# id — конфиденциальных данных в ней нет.
_ID_KEYS = {"id", "project_id", "user_id", "url"}


class Anonymizer:
    """Обезличиватель с накоплением сопоставления «значение ↔ метка».

    В отличие от разовой функции ``anonymize``, накапливает ``mapping`` между
    вызовами ``mask``. Это нужно для многошагового агентного цикла Hermes, где
    результаты нескольких инструментов обезличиваются согласованно (одно и то
    же значение получает одну и ту же метку во всех сообщениях диалога).
    """

    def __init__(self) -> None:
        self.mapping: Dict[str, str] = {}
        self._seen: Dict[str, str] = {}
        self._counters: Dict[str, int] = {}

    def _register(self, original: str, category: str) -> str:
        if original in self._seen:
            return self._seen[original]
        prefix = CATEGORY_PREFIX.get(category, "TERM")
        self._counters[category] = self._counters.get(category, 0) + 1
        placeholder = f"[{prefix}_{self._counters[category]}]"
        self.mapping[placeholder] = original
        self._seen[original] = placeholder
        return placeholder

    def mask(self, text: str, extra_terms: Optional[Dict[str, List[str]]] = None) -> str:
        """Обезличить текст, дополняя общий ``mapping``."""
        if not text:
            return text

        # 1) Явно переданные термины — сначала самые длинные, чтобы более
        #    длинные вхождения (напр. полное ФИО) не разбивались короткими.
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
                # Заменяем термин только как ОТДЕЛЬНЫЙ токен (границы слова), чтобы
                # короткий числовой код МВЗ (напр. «5») не портил цифры внутри
                # других чисел (id проекта «52», даты «2026»). \w в Python
                # покрывает латиницу, кириллицу и цифры.
                pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")
                if not pattern.search(text):
                    continue
                placeholder = self._register(term, category)
                text = pattern.sub(lambda m: placeholder, text)

        # 2) Контакты: email и телефоны.
        text = _EMAIL_RE.sub(lambda m: self._register(m.group(0), "contact"), text)
        text = _PHONE_RE.sub(lambda m: self._register(m.group(0), "contact"), text)

        # 3) Именованные сущности в «ёлочках» — маскируем содержимое, сохраняя кавычки.
        def _repl_quoted(m: "re.Match[str]") -> str:
            inner = m.group(1)
            if _PLACEHOLDER_RE.match(inner):  # уже метка, напр. «[PROJECT_1]»
                return m.group(0)
            return f"«{self._register(inner, 'project')}»"

        return _QUOTED_RE.sub(_repl_quoted, text)

    def mask_obj(self, obj, extra_terms: Optional[Dict[str, List[str]]] = None):
        """Обезличить структуру (dict/list/скаляр), маскируя ТОЛЬКО строки.

        Числа (id проектов, суммы, счётчики, метрики) и булевы значения не
        трогаются — так идентификаторы остаются валидными для последующих
        вызовов инструментов (иначе короткий числовой код МВЗ вроде «12» при
        строковой замене портит целочисленный ``id`` в JSON, и ИИ не может
        запросить детали проекта). Ключи-идентификаторы не маскируются, даже
        если пришли строкой.
        """
        if isinstance(obj, dict):
            return {
                k: (v if k in _ID_KEYS else self.mask_obj(v, extra_terms))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self.mask_obj(v, extra_terms) for v in obj]
        if isinstance(obj, str):
            return self.mask(obj, extra_terms)
        # int / float / bool / None — оставляем как есть.
        return obj

    def unmask(self, text: str) -> str:
        """Восстановить исходные значения из меток по накопленному mapping."""
        return deanonymize(text, self.mapping)


def anonymize(
    text: str,
    extra_terms: Optional[Dict[str, List[str]]] = None,
) -> Tuple[str, Dict[str, str]]:
    """Заменить чувствительные данные на метки (разовый вызов).

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
    az = Anonymizer()
    masked = az.mask(text, extra_terms)
    return masked, az.mapping


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
