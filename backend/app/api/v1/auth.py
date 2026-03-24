import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...auth import verify_password, hash_password, create_access_token, get_current_user
from ...schemas.user import Token, UserRead
from ... import settings_store
from ...services.email_service import send_registration_email

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
