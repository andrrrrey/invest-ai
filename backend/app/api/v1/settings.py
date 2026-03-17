from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ... import settings_store

router = APIRouter(prefix="/settings", tags=["settings"])

AI_MODEL = "gpt-4.1"


class SettingsUpdate(BaseModel):
    openai_api_key: Optional[str] = None


@router.get("/")
def get_settings() -> dict:
    """Return current settings (API key is masked)."""
    key = settings_store.get_openai_key()
    masked = None
    if key:
        visible = key[-4:] if len(key) >= 4 else key
        masked = "sk-..." + visible
    return {
        "openai_api_key_set": bool(key),
        "openai_api_key_masked": masked,
        "ai_model": AI_MODEL,
    }


@router.post("/")
def update_settings(body: SettingsUpdate) -> dict:
    """Save new settings."""
    if body.openai_api_key is not None:
        settings_store.set_openai_key(body.openai_api_key)
    return {"success": True}


@router.post("/test-connection")
def test_connection() -> dict:
    """Test that the stored API key works."""
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
