from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./invest_ai.db"
    OPENAI_API_KEY: Optional[str] = None
    SECRET_KEY: str = "change-me-in-production-use-long-random-string"
    CORS_ORIGINS: list[str] = ["*"]
    APP_ENV: str = "development"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480
    # Seed users created on first startup if users table is empty
    SEED_CEO_EMAIL: str = "ceo@example.com"
    SEED_CEO_PASSWORD: str = "changeme123"
    SEED_CEO_NAME: str = "CEO"
    SEED_CFO_EMAIL: str = "cfo@example.com"
    SEED_CFO_PASSWORD: str = "changeme123"
    SEED_CFO_NAME: str = "CFO"

    class Config:
        env_file = ".env"


settings = Settings()
