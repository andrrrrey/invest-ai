"""Отображение ФИО сотрудника «Фамилия Имя [Отчество]».

В профиле ФИО хранится как его ввели («Маргарита Кулеева», «Кулеева Маргарита»,
«Иван Иванович Иванов»). Для списков выбора имя приводится к виду
«Фамилия Имя». Порядок определяется по отчеству и типичным окончаниям
фамилий; если признаков нет — считается, что первым идёт имя.
Та же логика продублирована во фронтенде (``surnameFirst`` в js/auth.js).
"""

from __future__ import annotations

import re

_PATRONYMIC = re.compile(r"(вич|вна|чна|оглы|кызы|улы)$", re.IGNORECASE)
_SURNAME_STRONG = re.compile(r"(ов|ова|ев|ева|ёв|ёва|ский|ская|цкий|цкая|ской|енко|дзе|швили|ян|янц|ук|юк)$", re.IGNORECASE)
_SURNAME_WEAK = re.compile(r"(ин|ина|ын|ына|их|ых|ко)$", re.IGNORECASE)


def _is_patronymic(word: str) -> bool:
    return bool(_PATRONYMIC.search(word or ""))


def _surname_score(word: str) -> int:
    if _SURNAME_STRONG.search(word):
        return 2
    if _SURNAME_WEAK.search(word):
        return 1
    return 0


def surname_first(full_name: str | None) -> str:
    parts = (full_name or "").split()
    if len(parts) == 2:
        a, b = parts
        if _is_patronymic(b):            # «Иван Иванович» — фамилии нет
            return f"{a} {b}"
        if _surname_score(a) > _surname_score(b):
            return f"{a} {b}"            # уже «Фамилия Имя»
        return f"{b} {a}"                # «Имя Фамилия» → «Фамилия Имя»
    if len(parts) == 3:
        a, b, c = parts
        if _is_patronymic(b) and not _is_patronymic(c):
            return f"{c} {a} {b}"        # Имя Отчество Фамилия → Фамилия Имя Отчество
    return " ".join(parts)
