"""
File-based settings store.
Stores configuration (OpenAI/Anthropic API keys, active AI provider, etc.) in a JSON file on disk.
Environment variables OPENAI_API_KEY / ANTHROPIC_API_KEY always take precedence over file-stored keys.

Secret fields (``*_api_key``) are encrypted at rest with Fernet when the
``SETTINGS_ENCRYPTION_KEY`` environment variable is set. Any passphrase works —
it is stretched to a valid Fernet key via SHA-256. Values written before a key
was configured (or plaintext values) are read transparently and re-encrypted on
the next save (backward compatible).
"""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path(os.getenv("SETTINGS_PATH", "/data/settings.json"))

# Fields that must be encrypted at rest.
_SECRET_FIELDS = (
    "openai_api_key",
    "anthropic_api_key",
    "routerai_api_key",
    "mattermost_alert_webhook",
)
_ENC_PREFIX = "enc:v1:"

_warned_no_key = False


def _get_fernet():
    """Return a Fernet instance if SETTINGS_ENCRYPTION_KEY is configured, else None."""
    global _warned_no_key
    passphrase = os.getenv("SETTINGS_ENCRYPTION_KEY")
    if not passphrase:
        if not _warned_no_key:
            logger.warning(
                "SETTINGS_ENCRYPTION_KEY не задан — API-ключи AI хранятся в открытом "
                "виде. Задайте SETTINGS_ENCRYPTION_KEY для шифрования на диске."
            )
            _warned_no_key = True
        return None
    try:
        from cryptography.fernet import Fernet
        # Stretch any passphrase into a 32-byte urlsafe-base64 Fernet key.
        digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))
    except Exception:
        logger.exception("Не удалось инициализировать шифрование настроек")
        return None


def _decrypt_secrets(data: dict) -> dict:
    """Decrypt secret fields in-place-ish and return the dict (for reading)."""
    fernet = _get_fernet()
    for field in _SECRET_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val.startswith(_ENC_PREFIX):
            token = val[len(_ENC_PREFIX):]
            if fernet is None:
                # Cannot decrypt without the key — treat as unavailable.
                data[field] = None
                continue
            try:
                data[field] = fernet.decrypt(token.encode("utf-8")).decode("utf-8")
            except Exception:
                logger.exception("Не удалось расшифровать поле %s", field)
                data[field] = None
    return data


def _encrypt_secrets(data: dict) -> dict:
    """Return a copy of data with secret fields encrypted (when a key is set)."""
    fernet = _get_fernet()
    if fernet is None:
        return data  # no key configured — store as-is (plaintext, dev fallback)
    out = dict(data)
    for field in _SECRET_FIELDS:
        val = out.get(field)
        if isinstance(val, str) and val and not val.startswith(_ENC_PREFIX):
            token = fernet.encrypt(val.encode("utf-8")).decode("utf-8")
            out[field] = _ENC_PREFIX + token
    return out


def _load() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            return _decrypt_secrets(json.loads(_SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    _SETTINGS_FILE.write_text(
        json.dumps(_encrypt_secrets(data), indent=2, ensure_ascii=False),
        encoding="utf-8",
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


def get_nav_rate() -> float:
    """Return the current NAV exchange rate (rubles per coin). Default 10.1."""
    val = _load().get("nav_rate")
    try:
        return float(val) if val else 10.1
    except (TypeError, ValueError):
        return 10.1


def set_nav_rate(rate: float) -> None:
    data = _load()
    data["nav_rate"] = float(rate)
    _save(data)


def get_registration_domain() -> str | None:
    """Return the allowed email domain for self-registration."""
    return _load().get("registration_domain") or None


def set_registration_domain(domain: str) -> None:
    data = _load()
    data["registration_domain"] = domain.strip().lstrip("@").lower()
    _save(data)


def get_anthropic_key() -> str | None:
    """Return the effective Anthropic API key (env var takes priority)."""
    env_key = os.getenv("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    return _load().get("anthropic_api_key") or None


def set_anthropic_key(key: str) -> None:
    data = _load()
    data["anthropic_api_key"] = key.strip()
    _save(data)


def get_routerai_key() -> str | None:
    """Return the effective RouterAI API key (env var takes priority)."""
    env_key = os.getenv("ROUTERAI_API_KEY")
    if env_key:
        return env_key
    return _load().get("routerai_api_key") or None


def set_routerai_key(key: str) -> None:
    data = _load()
    data["routerai_api_key"] = key.strip()
    _save(data)


def get_routerai_model() -> str:
    """Return selected RouterAI model (default: anthropic/claude-sonnet-4.5)."""
    return _load().get("routerai_model") or "anthropic/claude-sonnet-4.5"


def set_routerai_model(model: str) -> None:
    data = _load()
    data["routerai_model"] = model.strip()
    _save(data)


def is_ai_enabled() -> bool:
    """Whether outbound calls to external AI providers are allowed.

    Sending project data (financial models, risks, plan/fact) to OpenAI /
    Anthropic / RouterAI is a data-egress decision. It is therefore opt-in:
    disabled by default in production (must be enabled explicitly by the CFO in
    Settings), enabled by default only in development for convenience.
    """
    from .config import settings
    val = _load().get("ai_enabled")
    if val is None:
        return not settings.is_production
    return bool(val)


def set_ai_enabled(enabled: bool) -> None:
    data = _load()
    data["ai_enabled"] = bool(enabled)
    _save(data)


def get_ai_provider() -> str:
    """Return active AI provider: 'openai' (default), 'anthropic', or 'routerai'."""
    return _load().get("ai_provider") or "openai"


def set_ai_provider(provider: str) -> None:
    if provider not in ("openai", "anthropic", "routerai"):
        raise ValueError(f"Unknown AI provider: {provider}")
    data = _load()
    data["ai_provider"] = provider
    _save(data)


# ── Hermes: обезличивание и оповещения ────────────────────────────

def get_mattermost_alert_webhook() -> str | None:
    """Incoming webhook служебного канала Mattermost для оповещений об ошибках.

    Переменная окружения MATTERMOST_ALERT_WEBHOOK имеет приоритет над файлом.
    """
    env = os.getenv("MATTERMOST_ALERT_WEBHOOK")
    if env:
        return env
    return _load().get("mattermost_alert_webhook") or None


def set_mattermost_alert_webhook(url: str) -> None:
    data = _load()
    data["mattermost_alert_webhook"] = (url or "").strip()
    _save(data)


def is_anonymize_enabled() -> bool:
    """Включено ли обезличивание перед отправкой в ИИ (по умолчанию ДА)."""
    val = _load().get("anonymize_enabled")
    if val is None:
        return True
    return bool(val)


def set_anonymize_enabled(enabled: bool) -> None:
    data = _load()
    data["anonymize_enabled"] = bool(enabled)
    _save(data)


def get_anonymize_round_amounts() -> bool:
    """Округлять ли финансовые суммы при обезличивании (по умолчанию НЕТ)."""
    return bool(_load().get("anonymize_round_amounts"))


def set_anonymize_round_amounts(enabled: bool) -> None:
    data = _load()
    data["anonymize_round_amounts"] = bool(enabled)
    _save(data)


def get_all() -> dict:
    return _load()
