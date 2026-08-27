import os

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from ... import settings_store
from ...auth import require_cfo
from ...services import alert_service

router = APIRouter(prefix="/settings", tags=["settings"])

OPENAI_MODEL = "gpt-5.4"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"

ROUTERAI_MODELS = {
    "anthropic/claude-opus-4.8": "Claude Opus 4.8",
    "anthropic/claude-sonnet-4.6": "Claude Sonnet 4.6",
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
}


class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    routerai_api_key: Optional[str] = None
    routerai_model: Optional[str] = None
    ai_provider: Optional[str] = None  # "openai" | "anthropic" | "routerai"
    ai_enabled: Optional[bool] = None
    investment_budget: Optional[float] = None
    registration_domain: Optional[str] = None
    # Hermes / Mattermost
    mattermost_base_url: Optional[str] = None
    mattermost_integration_url: Optional[str] = None
    mattermost_command_token: Optional[str] = None
    mattermost_bot_token: Optional[str] = None
    mattermost_alert_webhook: Optional[str] = None
    anonymize_enabled: Optional[bool] = None
    anonymize_round_amounts: Optional[bool] = None
    reminders_enabled: Optional[bool] = None
    hermes_write_enabled: Optional[bool] = None


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    visible = key[-4:] if len(key) >= 4 else key
    return "sk-..." + visible


@router.get("/")
def get_settings(_=Depends(require_cfo)) -> dict:
    """Return current settings (API keys are masked). CFO only."""
    openai_key = settings_store.get_openai_key()
    anthropic_key = settings_store.get_anthropic_key()
    routerai_key = settings_store.get_routerai_key()
    routerai_model = settings_store.get_routerai_model()
    provider = settings_store.get_ai_provider()
    if provider == "anthropic":
        active_model = ANTHROPIC_MODEL
    elif provider == "routerai":
        active_model = routerai_model
    else:
        active_model = OPENAI_MODEL
    return {
        "openai_api_key_set": bool(openai_key),
        "openai_api_key_masked": _mask_key(openai_key),
        "anthropic_api_key_set": bool(anthropic_key),
        "anthropic_api_key_masked": _mask_key(anthropic_key),
        "routerai_api_key_set": bool(routerai_key),
        "routerai_api_key_masked": _mask_key(routerai_key),
        "routerai_model": routerai_model,
        "routerai_models": ROUTERAI_MODELS,
        "ai_provider": provider,
        "ai_model": active_model,
        "ai_enabled": settings_store.is_ai_enabled(),
        "investment_budget": settings_store.get_investment_budget(),
        "registration_domain": settings_store.get_registration_domain(),
        # Hermes / Mattermost
        "mattermost_base_url": settings_store.get_mattermost_base_url(),
        "mattermost_integration_url": settings_store.get_mattermost_integration_url(),
        "mattermost_command_token_set": bool(settings_store.get_mattermost_command_token()),
        "mattermost_command_token_masked": _mask_key(settings_store.get_mattermost_command_token()),
        "mattermost_bot_token_set": bool(settings_store.get_mattermost_bot_token()),
        "mattermost_bot_token_masked": _mask_key(settings_store.get_mattermost_bot_token()),
        "mattermost_alert_webhook_set": bool(settings_store.get_mattermost_alert_webhook()),
        "mattermost_alert_webhook_masked": _mask_key(settings_store.get_mattermost_alert_webhook()),
        "anonymize_enabled": settings_store.is_anonymize_enabled(),
        "anonymize_round_amounts": settings_store.get_anonymize_round_amounts(),
        "reminders_enabled": settings_store.is_reminders_enabled(),
        "hermes_write_enabled": settings_store.is_hermes_write_enabled(),
        # Признак, что значение задано переменной окружения (env приоритетнее файла).
        "env_overrides": {
            "mattermost_base_url": bool(os.getenv("MATTERMOST_BASE_URL")),
            "mattermost_integration_url": bool(os.getenv("MATTERMOST_INTEGRATION_URL")),
            "mattermost_command_token": bool(os.getenv("MATTERMOST_COMMAND_TOKEN")),
            "mattermost_bot_token": bool(os.getenv("MATTERMOST_BOT_TOKEN")),
            "mattermost_alert_webhook": bool(os.getenv("MATTERMOST_ALERT_WEBHOOK")),
        },
    }


@router.post("/")
def update_settings(body: SettingsUpdate, _=Depends(require_cfo)) -> dict:
    """Save new settings. CFO only."""
    if body.openai_api_key is not None:
        settings_store.set_openai_key(body.openai_api_key)
    if body.anthropic_api_key is not None:
        settings_store.set_anthropic_key(body.anthropic_api_key)
    if body.routerai_api_key is not None:
        settings_store.set_routerai_key(body.routerai_api_key)
    if body.routerai_model is not None:
        settings_store.set_routerai_model(body.routerai_model)
    if body.ai_provider is not None:
        if body.ai_provider not in ("openai", "anthropic", "routerai"):
            raise HTTPException(status_code=400, detail="Неверное значение ai_provider. Допустимо: openai, anthropic, routerai")
        settings_store.set_ai_provider(body.ai_provider)
    if body.ai_enabled is not None:
        settings_store.set_ai_enabled(body.ai_enabled)
    if body.investment_budget is not None:
        settings_store.set_investment_budget(body.investment_budget)
    if body.registration_domain is not None:
        domain = body.registration_domain.strip().lstrip("@").lower()
        settings_store.set_registration_domain(domain)
    # Hermes / Mattermost
    if body.mattermost_base_url is not None:
        settings_store.set_mattermost_base_url(body.mattermost_base_url)
    if body.mattermost_integration_url is not None:
        settings_store.set_mattermost_integration_url(body.mattermost_integration_url)
    if body.mattermost_command_token is not None:
        settings_store.set_mattermost_command_token(body.mattermost_command_token)
    if body.mattermost_bot_token is not None:
        settings_store.set_mattermost_bot_token(body.mattermost_bot_token)
    if body.mattermost_alert_webhook is not None:
        settings_store.set_mattermost_alert_webhook(body.mattermost_alert_webhook)
    if body.anonymize_enabled is not None:
        settings_store.set_anonymize_enabled(body.anonymize_enabled)
    if body.anonymize_round_amounts is not None:
        settings_store.set_anonymize_round_amounts(body.anonymize_round_amounts)
    if body.reminders_enabled is not None:
        settings_store.set_reminders_enabled(body.reminders_enabled)
    if body.hermes_write_enabled is not None:
        settings_store.set_hermes_write_enabled(body.hermes_write_enabled)
    return {"success": True}


@router.post("/test-mattermost")
def test_mattermost(_=Depends(require_cfo)) -> dict:
    """Отправить тестовое оповещение в служебный канал Mattermost. CFO only."""
    if not settings_store.get_mattermost_alert_webhook():
        raise HTTPException(status_code=503, detail="Webhook служебного канала не настроен.")
    ok = alert_service.send_alert("Тестовое оповещение из настроек Hermes ✅")
    if not ok:
        raise HTTPException(status_code=502, detail="Не удалось отправить оповещение. Проверьте webhook.")
    return {"success": True}


@router.post("/test-connection")
def test_connection(_=Depends(require_cfo)) -> dict:
    """Test that the active provider's API key works. CFO only."""
    provider = settings_store.get_ai_provider()

    if provider == "anthropic":
        key = settings_store.get_anthropic_key()
        if not key:
            raise HTTPException(status_code=503, detail="Anthropic API ключ не настроен. Введите ключ в настройках.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=5,
                messages=[{"role": "user", "content": "Ответь словом OK"}],
            )
            return {"success": True, "model": ANTHROPIC_MODEL, "response": msg.content[0].text}
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    elif provider == "routerai":
        key = settings_store.get_routerai_key()
        if not key:
            raise HTTPException(status_code=503, detail="RouterAI API ключ не настроен. Введите ключ в настройках.")
        model = settings_store.get_routerai_model()
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=ROUTERAI_BASE_URL)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Ответь словом OK"}],
                max_tokens=5,
            )
            return {"success": True, "model": model, "response": resp.choices[0].message.content}
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    else:
        key = settings_store.get_openai_key()
        if not key:
            raise HTTPException(status_code=503, detail="OpenAI API ключ не настроен. Введите ключ в настройках.")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": "Ответь словом OK"}],
                max_completion_tokens=5,
            )
            return {"success": True, "model": resp.model, "response": resp.choices[0].message.content}
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))
