"""Общая настройка тестов.

Изолируем окружение (БД и файл настроек — во временный каталог) ДО импорта
приложения, т.к. движок SQLAlchemy и объект настроек создаются на импорте.
"""

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="hermes-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["SETTINGS_PATH"] = f"{_tmpdir}/settings.json"
os.environ["APP_ENV"] = "test"
# Никакого реального вебхука в тестах.
os.environ.pop("MATTERMOST_ALERT_WEBHOOK", None)

import pytest  # noqa: E402

from app.database import init_db, SessionLocal  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database():
    init_db()
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
