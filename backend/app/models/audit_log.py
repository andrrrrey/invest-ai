from sqlalchemy import Column, Integer, String, Text, JSON, Boolean, DateTime
from sqlalchemy.sql import func

from ..database import Base


class AuditLog(Base):
    """Сквозной журнал аудита обращений к ИИ и действий помощника.

    Фиксирует, кто, что и с каким результатом сделал, и подтверждает, что
    обезличивание применилось (``anonymized``). Сами конфиденциальные данные
    в журнал НЕ попадают — только метаданные и безопасные метки.
    Модель истории построена по образцу ``TrancheHistory``.
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # user | hermes | ai_gateway | system
    actor_type = Column(String, nullable=False, default="system")
    actor_id = Column(String, nullable=True)

    # напр. ai.chat | mcp.tool_call | hermes.approval_card_sent | status.change
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)

    # ok | error
    result = Column(String, nullable=False, default="ok")
    error_message = Column(Text, nullable=True)

    # Метаданные вызова ИИ.
    ai_provider = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    # Подтверждение применения обезличивания.
    anonymized = Column(Boolean, nullable=False, default=False)

    # Безопасные метаданные (без чувствительного текста): счётчики, длины и т.п.
    meta = Column(JSON, nullable=True)
