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
    from .models import user, project  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)

    # Idempotent column migrations for existing databases
    from sqlalchemy import text
    with engine.connect() as conn:
        for col_def in [
            "ALTER TABLE projects ADD COLUMN value_score_data JSON",
            "ALTER TABLE projects ADD COLUMN decision_route VARCHAR",
            "ALTER TABLE projects ADD COLUMN user_id INTEGER REFERENCES users(id)",
            "ALTER TABLE users ADD COLUMN avatar_url VARCHAR",
        ]:
            try:
                conn.execute(text(col_def))
                conn.commit()
            except Exception:
                pass  # column already exists

    # Seed initial CEO user if no users exist yet
    _seed_admin()


def _seed_admin():
    from .models.user import User
    from .auth import hash_password
    from .config import settings

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            seed_users = [
                User(
                    email=settings.SEED_CEO_EMAIL,
                    full_name=settings.SEED_CEO_NAME,
                    hashed_password=hash_password(settings.SEED_CEO_PASSWORD),
                    role="ceo",
                    is_active=True,
                ),
                User(
                    email=settings.SEED_CFO_EMAIL,
                    full_name=settings.SEED_CFO_NAME,
                    hashed_password=hash_password(settings.SEED_CFO_PASSWORD),
                    role="cfo",
                    is_active=True,
                ),
            ]
            for u in seed_users:
                db.add(u)
            db.commit()
            print(f"[init_db] Seed users created:")
            print(f"  CEO: {settings.SEED_CEO_EMAIL} / {settings.SEED_CEO_PASSWORD}")
            print(f"  CFO: {settings.SEED_CFO_EMAIL} / {settings.SEED_CFO_PASSWORD}")
    finally:
        db.close()
