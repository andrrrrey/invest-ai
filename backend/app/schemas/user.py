from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

VALID_ROLES = {"ceo", "cfo", "manager", "owner"}

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


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


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
