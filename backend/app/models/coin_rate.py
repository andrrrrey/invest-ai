from sqlalchemy import Column, Integer, Float, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class CoinRate(Base):
    """Курс Coin (₽ за 1 Coin), действующий с ``effective_date``.

    Курс на дату — последняя запись с ``effective_date <= дата``.
    """

    __tablename__ = "coin_rates"

    id = Column(Integer, primary_key=True, index=True)
    effective_date = Column(Date, nullable=False, unique=True, index=True)
    rate = Column(Float, nullable=False)
    comment = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    created_by = relationship("User")
