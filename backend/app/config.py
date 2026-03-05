from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./invest_ai.db"
    OPENAI_API_KEY: Optional[str] = None
    SECRET_KEY: str = "change-me-in-production-use-long-random-string"
    CORS_ORIGINS: list[str] = ["*"]
    APP_ENV: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
