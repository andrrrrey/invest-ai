from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..database import Base


class McpToken(Base):
    """Личный токен пользователя для подключения ИИ-программ по MCP.

    Пользователь (CEO/CFO/менеджер) сам создаёт и отзывает токены в профиле.
    Сам токен хранится только в виде SHA-256-хэша и показывается один раз при
    создании; ``token_prefix`` — начало токена, чтобы его можно было узнать в
    списке.
    """

    __tablename__ = "mcp_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    token_prefix = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
