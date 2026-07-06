from pydantic_settings import BaseSettings
from typing import Optional

# Placeholder value shipped in .env.example. Rejected at startup in production.
_DEFAULT_SECRET_KEY = "change-me-in-production-use-long-random-string"


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./invest_ai.db"
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    SECRET_KEY: str = _DEFAULT_SECRET_KEY
    CORS_ORIGINS: list[str] = ["*"]
    APP_ENV: str = "development"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 120
    # Seed users created on first startup if users table is empty.
    # Passwords default to None — if not provided via env, a strong random
    # password is generated and the account must be recovered via
    # "forgot password" (the password is never printed or stored in plaintext).
    SEED_CEO_EMAIL: str = "ceo@example.com"
    SEED_CEO_PASSWORD: Optional[str] = None
    SEED_CEO_NAME: str = "CEO"
    SEED_CFO_EMAIL: str = "cfo@example.com"
    SEED_CFO_PASSWORD: Optional[str] = None
    SEED_CFO_NAME: str = "CFO"
    # SMTP email settings for sending registration passwords
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "noreply@invest-ai.local"

    class Config:
        env_file = ".env"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() not in ("development", "dev", "local", "test")

    def validate_for_production(self) -> None:
        """Fail-fast on insecure configuration in a production environment.

        Called on application startup. In development the checks are skipped so
        local runs keep working with defaults.
        """
        if not self.is_production:
            return

        errors: list[str] = []

        if self.SECRET_KEY == _DEFAULT_SECRET_KEY or len(self.SECRET_KEY) < 32:
            errors.append(
                "SECRET_KEY must be set to a random value of at least 32 characters "
                "(the default placeholder is not allowed in production)."
            )

        if "*" in self.CORS_ORIGINS:
            errors.append(
                "CORS_ORIGINS must list explicit origins in production; "
                "'*' together with credentials is not allowed."
            )

        if errors:
            raise RuntimeError(
                "Небезопасная конфигурация для production:\n  - " + "\n  - ".join(errors)
            )


settings = Settings()
