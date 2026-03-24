from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .schemas.user import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours


# ---------- password helpers ----------

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# ---------- JWT helpers ----------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenData:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        sub: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("user_id")
        if sub is None or role is None or user_id is None:
            raise credentials_exc
        return TokenData(sub=sub, role=role, user_id=user_id)
    except JWTError:
        raise credentials_exc


# ---------- FastAPI dependencies ----------

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Require a valid JWT and return the User ORM object."""
    from .models.user import User  # lazy import to avoid circular deps

    token_data = decode_token(token)
    user = db.query(User).filter(User.email == token_data.sub).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден или деактивирован",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
):
    """Return User or None without raising."""
    if not token:
        return None
    try:
        from .models.user import User
        token_data = decode_token(token)
        user = db.query(User).filter(User.email == token_data.sub).first()
        return user if user and user.is_active else None
    except Exception:
        return None


def require_approver(current_user=Depends(get_current_user)):
    """Allow only cfo and manager roles."""
    if current_user.role not in ("cfo", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль CFO или Менеджера.",
        )
    return current_user


def require_cfo(current_user=Depends(get_current_user)):
    """Allow only cfo role."""
    if current_user.role != "cfo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль CFO.",
        )
    return current_user


def require_not_owner(current_user=Depends(get_current_user)):
    """Allow ceo, cfo, manager — block owner."""
    if current_user.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для этого действия.",
        )
    return current_user
