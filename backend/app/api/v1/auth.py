import os
import secrets
import string
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...auth import verify_password, hash_password, create_access_token, get_current_user
from ...schemas.user import Token, UserRead, UserProfileUpdate, ChangePasswordRequest
from ... import settings_store
from ...config import settings
from ...services.email_service import send_registration_email

AVATARS_DIR = os.environ.get("AVATARS_DIR", "/data/avatars")

# ---------- OIDC discovery cache ----------

_oidc_config_cache: dict = {}


def _get_oidc_config() -> dict:
    """Fetch and cache OIDC discovery document from the provider's well-known endpoint."""
    if _oidc_config_cache:
        return _oidc_config_cache

    if not settings.OIDC_ISSUER_URL:
        raise HTTPException(status_code=501, detail="SSO не настроен (OIDC_ISSUER_URL не задан)")

    discovery_url = settings.OIDC_ISSUER_URL.rstrip("/") + "/.well-known/openid-configuration"
    try:
        resp = httpx.get(discovery_url, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Не удалось получить OIDC конфигурацию: {exc}")

    _oidc_config_cache.update(resp.json())
    return _oidc_config_cache

router = APIRouter(prefix="/auth", tags=["auth"])


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class RegisterRequest(BaseModel):
    email: str
    full_name: str


@router.post("/token", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Login with email + password, returns JWT token."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт деактивирован",
        )

    token = create_access_token(data={
        "sub": user.email,
        "role": user.role,
        "user_id": user.id,
    })
    return Token(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        role=user.role,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    """Return currently authenticated user info."""
    return current_user


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Self-registration for applicants (owner role). Email domain must match CFO-configured domain."""
    allowed_domain = settings_store.get_registration_domain()
    if not allowed_domain:
        raise HTTPException(
            status_code=403,
            detail="Самостоятельная регистрация отключена. Обратитесь к администратору.",
        )

    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Некорректный email.")

    domain = email.split("@", 1)[1]
    if domain != allowed_domain:
        raise HTTPException(
            status_code=403,
            detail=f"Регистрация разрешена только для домена @{allowed_domain}.",
        )

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Пользователь с таким email уже зарегистрирован.",
        )

    password = _generate_password()
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        hashed_password=hash_password(password),
        role="owner",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()

    try:
        send_registration_email(email, body.full_name.strip(), password)
    except Exception as exc:
        # Roll back user creation if email sending fails so the user can retry
        db.delete(user)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail=f"Не удалось отправить письмо: {exc}",
        )

    return {"detail": "Регистрация успешна. Пароль отправлен на ваш email."}


@router.put("/me", response_model=UserRead)
def update_me(
    body: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update own profile (full_name and/or email)."""
    if body.email is not None:
        email = body.email.strip().lower()
        if "@" not in email:
            raise HTTPException(status_code=422, detail="Некорректный email.")
        existing = db.query(User).filter(User.email == email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email уже используется другим пользователем.")
        current_user.email = email

    if body.full_name is not None:
        name = body.full_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Имя не может быть пустым.")
        current_user.full_name = name

    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/change-password", status_code=200)
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change own password. Requires current password for verification."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль.")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="Новый пароль должен содержать не менее 6 символов.")
    current_user.hashed_password = hash_password(body.new_password)
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"detail": "Пароль успешно изменён."}


@router.delete("/me", status_code=200)
def delete_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete own account (soft-delete by deactivating)."""
    current_user.is_active = False
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"detail": "Аккаунт удалён."}


@router.post("/avatar", response_model=UserRead)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload and save user avatar. Expects a JPEG/PNG/WebP image."""
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=422, detail="Разрешены только изображения JPEG, PNG, WebP.")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Размер файла не должен превышать 5 МБ.")

    os.makedirs(AVATARS_DIR, exist_ok=True)

    # Delete old avatar file if it exists
    if current_user.avatar_url:
        old_filename = current_user.avatar_url.split("/")[-1]
        old_path = os.path.join(AVATARS_DIR, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    ext = "jpg" if file.content_type == "image/jpeg" else file.content_type.split("/")[1]
    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(AVATARS_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    current_user.avatar_url = f"/avatars/{filename}"
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    return current_user


# ---------- SSO / OIDC endpoints ----------

@router.get("/sso/login")
def sso_login():
    """Redirect the browser to the OIDC provider's authorization endpoint."""
    if not settings.OIDC_CLIENT_ID or not settings.OIDC_ISSUER_URL:
        raise HTTPException(status_code=501, detail="SSO не настроен на сервере")

    oidc_cfg = _get_oidc_config()
    state = secrets.token_urlsafe(32)

    query = urlencode({
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": "openid email profile",
        "state": state,
    })
    auth_url = oidc_cfg["authorization_endpoint"] + "?" + query

    response = RedirectResponse(url=auth_url, status_code=302)
    # Store state in a short-lived cookie for CSRF protection
    response.set_cookie(
        key="sso_state",
        value=state,
        httponly=True,
        samesite="lax",
        max_age=300,
        secure=settings.APP_ENV == "production",
    )
    return response


@router.get("/sso/callback")
def sso_callback(
    code: str,
    state: str,
    sso_state: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Handle the authorization code callback from the OIDC provider."""
    if not sso_state or sso_state != state:
        raise HTTPException(status_code=400, detail="Неверный state параметр (возможна CSRF-атака)")

    oidc_cfg = _get_oidc_config()

    # Exchange authorization code for tokens
    try:
        token_resp = httpx.post(
            oidc_cfg["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.OIDC_REDIRECT_URI,
                "client_id": settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
            },
            timeout=10,
        )
        token_resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка получения токена от SSO: {exc}")

    access_token_oidc = token_resp.json().get("access_token")

    # Get user info from provider
    try:
        userinfo_resp = httpx.get(
            oidc_cfg["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token_oidc}"},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка получения данных пользователя от SSO: {exc}")

    userinfo = userinfo_resp.json()
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="SSO провайдер не вернул email пользователя")

    full_name = (
        userinfo.get("name")
        or userinfo.get("preferred_username")
        or email
    )

    # Find existing user or create a new one with default role
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password="",   # SSO-only account; password login disabled
            role=settings.SSO_DEFAULT_ROLE,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")

    # Issue our own JWT so the frontend works identically to password login
    jwt_token = create_access_token(data={
        "sub": user.email,
        "role": user.role,
        "user_id": user.id,
    })

    # Redirect to login page with token in query string;
    # login.html JS will call saveAuth() and immediately replace the URL.
    params = urlencode({
        "access_token": jwt_token,
        "token_type": "bearer",
        "user_id": user.id,
        "role": user.role,
        "full_name": user.full_name,
    })
    response = RedirectResponse(url=f"/login.html?{params}", status_code=302)
    response.delete_cookie("sso_state")
    return response
