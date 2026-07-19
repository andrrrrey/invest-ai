import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db
from ...models.user import User
from ...auth import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    generate_password,
)
from ...schemas.user import Token, UserRead, UserProfileUpdate, ChangePasswordRequest
from ...schemas.user import validate_password_strength
from ... import settings_store
from ...services.email_service import send_registration_email, send_password_reset_email

AVATARS_DIR = os.environ.get("AVATARS_DIR", "/data/avatars")

router = APIRouter(prefix="/auth", tags=["auth"])


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
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
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

    # Create the account with an unknown, cryptographically-random password.
    # The user never receives a plaintext password by email — instead we send a
    # one-time invite link (reset token) so they set their own password. This
    # avoids leaking credentials via email.
    invite_token = secrets.token_urlsafe(32)
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        hashed_password=hash_password(generate_password()),
        role="owner",
        is_active=True,
        password_reset_token=invite_token,
        password_reset_expires=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/reset-password.html?token={invite_token}"

    try:
        send_registration_email(email, body.full_name.strip(), invite_url)
    except Exception as exc:
        # Roll back user creation if email sending fails so the user can retry
        db.delete(user)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail=f"Не удалось отправить письмо: {exc}",
        )

    return {"detail": "Регистрация успешна. Ссылка для установки пароля отправлена на ваш email."}


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
    try:
        validate_password_strength(body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
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


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password", status_code=200)
def forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Send password reset email. Always returns 200 to avoid email enumeration."""
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        return {"detail": "Если этот email зарегистрирован, вы получите письмо со ссылкой для сброса пароля."}

    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    reset_url = f"{base_url}/reset-password.html?token={token}"

    try:
        send_password_reset_email(email, user.full_name, reset_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Не удалось отправить письмо: {exc}")

    return {"detail": "Если этот email зарегистрирован, вы получите письмо со ссылкой для сброса пароля."}


@router.post("/reset-password", status_code=200)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using a valid token."""
    try:
        validate_password_strength(body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    user = db.query(User).filter(User.password_reset_token == body.token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Недействительная или истёкшая ссылка сброса пароля.")

    # SQLite stores DateTime(timezone=True) columns as naive values, so normalize
    # to UTC-aware before comparing against the timezone-aware "now".
    expires = user.password_reset_expires
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires is None or datetime.now(timezone.utc) > expires:
        user.password_reset_token = None
        user.password_reset_expires = None
        db.commit()
        raise HTTPException(status_code=400, detail="Ссылка для сброса пароля истекла. Запросите новую.")

    user.hashed_password = hash_password(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"detail": "Пароль успешно изменён. Войдите с новым паролем."}


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
    # Unguessable filename: 128-bit random token, no user-id prefix, so avatar
    # URLs cannot be enumerated from a user id (the static mount is public).
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(AVATARS_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    current_user.avatar_url = f"/avatars/{filename}"
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    return current_user


# ─────────────────────────── SSO / OIDC ────────────────────────────
# Optional single sign-on via any OpenID Connect provider (e.g. Keycloak).
# Enabled only when OIDC_ISSUER_URL is configured; otherwise these endpoints
# return 501. The flow: /sso/login redirects to the IdP, the IdP redirects back
# to /sso/callback, we validate the id_token, provision the user if new, and
# issue our OWN JWT so the rest of the app is identical to password login.

_oidc_config_cache: dict = {}
_jwks_cache: dict = {}


def _get_oidc_config() -> dict:
    """Fetch and cache the provider's OIDC discovery document."""
    if _oidc_config_cache:
        return _oidc_config_cache
    if not settings.OIDC_ISSUER_URL:
        raise HTTPException(status_code=501, detail="SSO не настроен (OIDC_ISSUER_URL не задан)")
    discovery_url = settings.OIDC_ISSUER_URL.rstrip("/") + "/.well-known/openid-configuration"
    try:
        resp = httpx.get(discovery_url, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось получить OIDC discovery: {exc}")
    _oidc_config_cache.update(resp.json())
    return _oidc_config_cache


def _get_signing_key(kid: Optional[str]) -> dict:
    """Return the JWKS key matching `kid`, refetching JWKS on a miss (key rotation)."""
    def _find(keys):
        for k in keys:
            if k.get("kid") == kid:
                return k
        return None

    key = _find(_jwks_cache.get("keys", []))
    if key is None:
        jwks_uri = _get_oidc_config().get("jwks_uri")
        if not jwks_uri:
            raise HTTPException(status_code=502, detail="OIDC провайдер не сообщил jwks_uri")
        try:
            resp = httpx.get(jwks_uri, timeout=10)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Не удалось получить JWKS: {exc}")
        _jwks_cache.clear()
        _jwks_cache.update(resp.json())
        key = _find(_jwks_cache.get("keys", []))
    if key is None:
        raise HTTPException(status_code=401, detail="Не найден ключ подписи id_token (kid)")
    return key


@router.get("/sso/login")
def sso_login():
    """Redirect the browser to the OIDC provider's authorization endpoint."""
    if not settings.OIDC_ISSUER_URL or not settings.OIDC_CLIENT_ID:
        raise HTTPException(status_code=501, detail="SSO не настроен на сервере")

    oidc_cfg = _get_oidc_config()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    query = urlencode({
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
    })
    auth_url = oidc_cfg["authorization_endpoint"] + "?" + query

    response = RedirectResponse(url=auth_url, status_code=302)
    # Short-lived cookies bind this browser to the state/nonce we generated
    # (CSRF + replay protection). httponly so JS can't read them.
    cookie_kwargs = dict(httponly=True, samesite="lax", max_age=300, secure=settings.is_production)
    response.set_cookie("sso_state", state, **cookie_kwargs)
    response.set_cookie("sso_nonce", nonce, **cookie_kwargs)
    return response


@router.get("/sso/callback")
def sso_callback(
    code: str,
    state: str,
    sso_state: Optional[str] = Cookie(default=None),
    sso_nonce: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Handle the authorization-code callback: validate, provision, issue our JWT."""
    # 1. CSRF: the state echoed by the IdP must match our cookie.
    if not sso_state or not secrets.compare_digest(sso_state, state):
        raise HTTPException(status_code=400, detail="Неверный state (возможна CSRF-атака)")

    oidc_cfg = _get_oidc_config()

    # 2. Exchange the authorization code for tokens.
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
        raise HTTPException(status_code=502, detail=f"Ошибка обмена кода в SSO: {exc}")

    tokens = token_resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="SSO провайдер не вернул id_token")

    # 3. Validate the id_token: signature via JWKS, plus issuer/audience/expiry.
    # Pass the OIDC access_token so python-jose can verify the id_token's at_hash
    # claim (which providers like Keycloak always include); without it, jose
    # aborts with "No access_token provided to compare against at_hash claim".
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Некорректный id_token: {exc}")
    key = _get_signing_key(header.get("kid"))  # may raise 401/502 — intentionally not swallowed
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=settings.OIDC_CLIENT_ID,
            issuer=settings.OIDC_ISSUER_URL,
            access_token=tokens.get("access_token"),
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Недействительный id_token: {exc}")

    # 4. Replay protection: nonce in the token must match the one we issued.
    if not sso_nonce or claims.get("nonce") != sso_nonce:
        raise HTTPException(status_code=400, detail="Неверный nonce (возможна replay-атака)")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="SSO провайдер не вернул email пользователя")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=403, detail="Email в SSO не подтверждён провайдером")

    full_name = claims.get("name") or claims.get("preferred_username") or email

    # 5. Find or JIT-provision the user, then issue our own JWT.
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

    jwt_token = create_access_token(data={
        "sub": user.email,
        "role": user.role,
        "user_id": user.id,
    })

    # 6. Hand the token to the SPA via the URL *fragment* (not the query string):
    # fragments are never sent to the server or in the Referer header, so the JWT
    # can't leak into access logs. login.html reads it from location.hash.
    params = urlencode({
        "access_token": jwt_token,
        "token_type": "bearer",
        "user_id": user.id,
        "role": user.role,
        "full_name": user.full_name,
    })
    response = RedirectResponse(url=f"/login.html#{params}", status_code=302)
    response.delete_cookie("sso_state")
    response.delete_cookie("sso_nonce")
    return response
