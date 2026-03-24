"""
File-based settings store.
Stores configuration (OpenAI API key, etc.) in a JSON file on disk.
Environment variable OPENAI_API_KEY always takes precedence over file-stored key.
"""

import json
import os
from pathlib import Path

_SETTINGS_FILE = Path(os.getenv("SETTINGS_PATH", "settings.json"))


def _load() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    _SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_openai_key() -> str | None:
    """Return the effective OpenAI API key (env var takes priority)."""
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key
    return _load().get("openai_api_key") or None


def set_openai_key(key: str) -> None:
    data = _load()
    data["openai_api_key"] = key.strip()
    _save(data)


def get_investment_budget() -> float | None:
    return _load().get("investment_budget") or None


def set_investment_budget(budget: float) -> None:
    data = _load()
    data["investment_budget"] = budget
    _save(data)


def get_registration_domain() -> str | None:
    """Return the allowed email domain for self-registration."""
    return _load().get("registration_domain") or None


def set_registration_domain(domain: str) -> None:
    data = _load()
    data["registration_domain"] = domain.strip().lstrip("@").lower()
    _save(data)


def get_all() -> dict:
    return _load()
