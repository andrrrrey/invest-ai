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
    from . import models  # noqa: F401 — imports __init__.py, registers all models

    # create_all(checkfirst=True) inspects then creates missing tables, but with
    # multiple uvicorn workers two processes can inspect concurrently, both see a
    # brand-new table as missing, and the loser gets "table already exists" on
    # first creation. Treat that as benign — the other worker created it — so a
    # deploy that adds a new table doesn't crash a worker on startup.
    from sqlalchemy.exc import OperationalError, ProgrammingError
    import logging
    _log = logging.getLogger(__name__)
    try:
        Base.metadata.create_all(bind=engine)
    except (OperationalError, ProgrammingError) as exc:
        if "already exists" in str(exc).lower():
            _log.warning("Таблица уже создана конкурентным воркером — пропускаем: %s", exc)
        else:
            raise

    # Idempotent column migrations for databases created by an older schema.
    # (table, column, DDL type used in "ADD COLUMN <column> <type>")
    migrations = [
        ("projects", "value_score_data", "JSON"),
        ("projects", "decision_route", "VARCHAR"),
        ("projects", "user_id", "INTEGER REFERENCES users(id)"),
        ("users", "avatar_url", "VARCHAR"),
        ("projects", "status_history", "JSON"),
        ("users", "password_reset_token", "VARCHAR"),
        ("users", "password_reset_expires", "TIMESTAMP"),
        ("projects", "smart_contract_data", "JSON"),
        ("projects", "forecast_data", "JSON"),
        ("users", "mattermost_email", "VARCHAR"),
        ("projects", "rejection_reason", "TEXT"),
    ]

    # Check which columns already exist via the dialect-agnostic Inspector,
    # then add only the missing ones. Each ALTER runs in its own transaction
    # with an explicit rollback on error so a single failure can't leave a
    # PostgreSQL connection in an aborted-transaction state (unlike the old
    # swallow-every-exception loop, which only worked on SQLite).
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, column, ddl_type in migrations:
        if table not in existing_tables:
            continue  # create_all above already built the full current schema
        existing_columns = {col["name"] for col in inspector.get_columns(table)}
        if column in existing_columns:
            continue
        with engine.connect() as conn:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                conn.commit()
            except Exception:
                conn.rollback()  # keep the connection usable on Postgres

    # Seed initial CEO user if no users exist yet
    _seed_admin()
    # Ensure the read-only service account for the Hermes assistant exists.
    _seed_service_account()


def _seed_admin():
    from .models.user import User
    from .auth import hash_password, generate_password
    from .config import settings

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            # Use env-provided seed passwords when set; otherwise generate a
            # strong random password that is never printed or persisted in
            # plaintext. The account is then recovered via "forgot password".
            ceo_pw = settings.SEED_CEO_PASSWORD or generate_password()
            cfo_pw = settings.SEED_CFO_PASSWORD or generate_password()
            seed_users = [
                User(
                    email=settings.SEED_CEO_EMAIL,
                    full_name=settings.SEED_CEO_NAME,
                    hashed_password=hash_password(ceo_pw),
                    role="ceo",
                    is_active=True,
                ),
                User(
                    email=settings.SEED_CFO_EMAIL,
                    full_name=settings.SEED_CFO_NAME,
                    hashed_password=hash_password(cfo_pw),
                    role="cfo",
                    is_active=True,
                ),
            ]
            for u in seed_users:
                db.add(u)
            db.commit()
            print("[init_db] Seed users created (CEO, CFO).")
            if not settings.SEED_CEO_PASSWORD or not settings.SEED_CFO_PASSWORD:
                print(
                    "[init_db] A random password was generated for accounts without "
                    "SEED_*_PASSWORD set. Use «Забыли пароль?» to set a password, or "
                    "provide SEED_CEO_PASSWORD / SEED_CFO_PASSWORD via environment."
                )
    finally:
        db.close()


def _seed_service_account():
    """Создать служебный (read-only) аккаунт помощника Hermes, если его нет.

    Роль ``ceo`` в системе заблокирована на создание/редактирование/удаление и
    отправку на согласование — то есть это естественный read-only профиль.
    Идентичность используется для аудита обращений помощника.
    """
    from .models.user import User
    from .auth import hash_password, generate_password
    from .config import settings

    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.email == settings.HERMES_BOT_EMAIL).first()
        if exists is None:
            db.add(
                User(
                    email=settings.HERMES_BOT_EMAIL,
                    full_name=settings.HERMES_BOT_NAME,
                    hashed_password=hash_password(generate_password()),
                    role="ceo",
                    is_active=True,
                )
            )
            db.commit()
            print("[init_db] Hermes service account created (read-only, role=ceo).")
    finally:
        db.close()
