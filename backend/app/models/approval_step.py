from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class ApprovalStep(Base):
    """Этап маршрута согласования (контракта или проекта приказа).

    Маршрут — упорядоченный набор этапов одного ``cycle``. Этапы проходят
    строго последовательно: следующий становится ``active`` только после
    решения «Согласовано» по предыдущему. Возврат на доработку закрывает цикл;
    повторная отправка создаёт новый цикл.
    """

    __tablename__ = "approval_steps"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    route = Column(String, nullable=False, default="contract")  # contract | order
    cycle = Column(Integer, nullable=False, default=1)
    order_index = Column(Integer, nullable=False, default=0)
    role_key = Column(String, nullable=False)  # cb | customer | treasurer | cfo | lawyer | ceo
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # waiting | active | approved | rework | cancelled
    status = Column(String, nullable=False, default="waiting")
    sent_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    comment = Column(Text, nullable=True)
    reminded_at = Column(DateTime(timezone=True), nullable=True)
    attachment_id = Column(Integer, ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project")
    assignee = relationship("User", foreign_keys=[assignee_id])
    decided_by = relationship("User", foreign_keys=[decided_by_id])
