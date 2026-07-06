import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
