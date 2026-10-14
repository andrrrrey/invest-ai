"""Упоминания сотрудников в комментариях: «@Фамилия», «@Фамилия Имя»,
«@Имя Фамилия» (а также «#Фамилия»).

Сопоставление идёт по словам ФИО активных пользователей без учёта регистра.
Если по одному слову подходят несколько сотрудников, второе слово уточняет
выбор; иначе уведомляются все совпавшие.
"""

from __future__ import annotations

import re
from typing import List

from sqlalchemy.orm import Session

from ..models.user import User

_WORD = r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+"
_MENTION_RE = re.compile(rf"(?<![\w@#])[@#]({_WORD})(?:[  ]+({_WORD}))?")


def _tokens(full_name: str) -> set:
    return {t.lower().replace("ё", "е") for t in re.findall(_WORD, full_name or "")}


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def parse_mentions(db: Session, text: str, *, exclude_user_id: int | None = None) -> List[User]:
    from ..config import settings
    users = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .filter(User.email != settings.HERMES_BOT_EMAIL)
        .all()
    )
    index = [(u, _tokens(u.full_name)) for u in users]
    found: dict[int, User] = {}
    for first, second in _MENTION_RE.findall(text or ""):
        candidates = [u for u, toks in index if _norm(first) in toks]
        if second:
            narrowed = [u for u in candidates if _norm(second) in _tokens(u.full_name)]
            if narrowed:
                candidates = narrowed
        for u in candidates:
            if u.id != exclude_user_id:
                found[u.id] = u
    return list(found.values())
