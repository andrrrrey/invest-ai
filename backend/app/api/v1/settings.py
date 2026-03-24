from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from ... import settings_store
from ...auth import require_cfo

router = APIRouter(prefix="/settings", tags=["settings"])

AI_MODEL = "gpt-4.1"


class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    investment_budget: Optional[float] = None
    registration_domain: Optional[str] = None


@router.get("/")
def get_settings(_=Depends(require_cfo)) -> dict:
    """Return current settings (API key is masked). CFO only."""
    key = settings_store.get_openai_key()
    masked = None
    if key:
        visible = key[-4:] if len(key) >= 4 else key
        masked = "sk-..." + visible
    return {
        "openai_api_key_set": bool(key),
        "openai_api_key_masked": masked,
        "ai_model": AI_MODEL,
        "investment_budget": settings_store.get_investment_budget(),
        "registration_domain": settings_store.get_registration_domain(),
    }


@router.post("/")
def update_settings(body: SettingsUpdate, _=Depends(require_cfo)) -> dict:
    """Save new settings. CFO only."""
    if body.openai_api_key is not None:
        settings_store.set_openai_key(body.openai_api_key)
    if body.investment_budget is not None:
        settings_store.set_investment_budget(body.investment_budget)
    if body.registration_domain is not None:
        domain = body.registration_domain.strip().lstrip("@").lower()
        settings_store.set_registration_domain(domain)
    return {"success": True}


@router.post("/test-connection")
def test_connection(_=Depends(require_cfo)) -> dict:
    """Test that the stored API key works. CFO only."""
    key = settings_store.get_openai_key()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="API ключ не настроен. Введите ключ в настройках.",
        )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": "Ответь словом OK"}],
            max_tokens=5,
        )
        return {"success": True, "model": resp.model, "response": resp.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
