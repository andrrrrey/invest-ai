from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

VALID_ROLES = {"ceo", "cfo", "manager", "owner"}

MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
    """Enforce a minimal password policy.

    Raises ValueError with a Russian message if the password is too weak.
    Policy: at least 8 characters, containing both letters and digits.
    """
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов."
        )
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        raise ValueError("Пароль должен содержать буквы и цифры.")

ROLE_LABELS = {
    "ceo": "CEO",
    "cfo": "CFO",
    "manager": "Менеджер",
    "owner": "Заявитель",
}


class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = "owner"

    def validate_role(self):
        if self.role not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {VALID_ROLES}")


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    mattermost_email: Optional[str] = None


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    avatar_url: Optional[str] = None
    mattermost_email: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    mattermost_email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    full_name: str


class TokenData(BaseModel):
    sub: str          # email
    role: str
    user_id: int
