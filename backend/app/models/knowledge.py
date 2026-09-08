from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func

from ..database import Base


class KnowledgeEntry(Base):
    """Запись базы знаний Hermes — «дообучение» бота новыми знаниями.

    Курируется CFO через UI. Используется двумя способами:
      - ``pinned=True`` — короткое знание всегда добавляется в системный промпт
        агента (``hermes_agent``);
      - через read-инструмент ``search_knowledge`` — семантический поиск по всей
        активной базе (эмбеддинги + косинусная близость, фолбэк — keyword).

    Вектор ``embedding`` считается при создании/изменении записи
    (``knowledge_service.reindex``). ``embedding_model`` фиксирует, какой моделью
    посчитан вектор, — чтобы инвалидировать его при смене модели эмбеддингов.
    """

    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    # Список тегов (строки). JSON для переносимости между SQLite/PostgreSQL.
    tags = Column(JSON, nullable=True)
    pinned = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    # Вектор эмбеддинга контента (список float). Может отсутствовать, если
    # эмбеддинги были недоступны при сохранении — тогда запись доступна только
    # keyword-поиску.
    embedding = Column(JSON, nullable=True)
    embedding_model = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
