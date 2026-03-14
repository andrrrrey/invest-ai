from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from .models import project  # noqa: F401 — registers models
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing databases (idempotent migration)
    with engine.connect() as conn:
        for col_def in [
            "ALTER TABLE projects ADD COLUMN value_score_data JSON",
            "ALTER TABLE projects ADD COLUMN decision_route VARCHAR",
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(col_def))
                conn.commit()
            except Exception:
                pass  # column already exists
