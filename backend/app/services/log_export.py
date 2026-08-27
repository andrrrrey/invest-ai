"""
Чтение и фильтрация системных логов для выгрузки на экране «Аудит».

Логи пишутся в ротируемый файл ``LOG_FILE`` (см. logging_config). Здесь мы их
читаем, фильтруем по уровню/подстроке и отдаём «хвост» — для скачивания или
отправки разработчику. Конфиденциальные данные в логи не пишутся (обезличивание
+ аудит без сырого текста), поэтому выгрузка безопасна; доступ — только CFO.
"""

from __future__ import annotations

import glob
import os
from typing import List, Optional

# Уровень -> какие уровни включать (по возрастанию серьёзности).
_LEVELS_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _log_file() -> str:
    return os.environ.get("LOG_FILE", "/data/logs/app.log")


def _log_files_oldest_first() -> List[str]:
    """Текущий файл + ротированные бэкапы (``app.log.1`` … ) по возрастанию времени."""
    base = _log_file()
    if not base:
        return []
    backups = sorted(
        glob.glob(base + ".*"),
        key=lambda p: int(p.rsplit(".", 1)[-1]) if p.rsplit(".", 1)[-1].isdigit() else 0,
        reverse=True,
    )
    # backups: .5 .4 ... .1 (старые -> новые), затем текущий
    return backups + [base]


def _levels_at_or_above(level: Optional[str]) -> Optional[set]:
    if not level:
        return None
    level = level.upper()
    if level not in _LEVELS_ORDER:
        return None
    idx = _LEVELS_ORDER.index(level)
    return set(_LEVELS_ORDER[idx:])


def _line_matches(line: str, levels: Optional[set], contains: Optional[str]) -> bool:
    if levels is not None:
        # В JSON-строке уровень как: "level": "ERROR"
        if not any(f'"level": "{lv}"' in line for lv in levels):
            return False
    if contains:
        if contains.lower() not in line.lower():
            return False
    return True


def read_logs(
    level: Optional[str] = None,
    contains: Optional[str] = None,
    max_lines: int = 1000,
) -> str:
    """Вернуть последние ``max_lines`` строк логов с фильтром по уровню/подстроке.

    ``level`` — минимальный уровень (включаются он и более серьёзные).
    """
    max_lines = max(1, min(int(max_lines or 1000), 50000))
    levels = _levels_at_or_above(level)

    collected: List[str] = []
    for path in _log_files_oldest_first():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    if _line_matches(line, levels, contains):
                        collected.append(line)
        except FileNotFoundError:
            continue
        except Exception:
            continue

    if not collected:
        return ""
    return "\n".join(collected[-max_lines:])
