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
    # SSO / OIDC settings (Keycloak or any OpenID Connect-compatible provider).
    # SSO is OFF unless OIDC_ISSUER_URL is set. When configured, users can sign
    # in via /api/v1/auth/sso/login; new accounts are provisioned with SSO_DEFAULT_ROLE.
    OIDC_ISSUER_URL: Optional[str] = None   # e.g. https://keycloak.example.com/realms/myrealm
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None
    OIDC_REDIRECT_URI: str = "http://localhost/api/v1/auth/sso/callback"
    SSO_DEFAULT_ROLE: str = "owner"         # role assigned to new users created via SSO
    # Hermes: служебный incoming-webhook Mattermost для оповещений об ошибках.
    # Env-переменная имеет приоритет над значением в файле настроек.
    MATTERMOST_ALERT_WEBHOOK: Optional[str] = None
    # Токен верификации входящих slash-команд/вебхуков Mattermost.
    MATTERMOST_COMMAND_TOKEN: Optional[str] = None
    # Токен бота Mattermost (карточки согласования).
    MATTERMOST_BOT_TOKEN: Optional[str] = None
    # Базовый URL сервера Mattermost для вызовов bot API.
    MATTERMOST_BASE_URL: Optional[str] = None
    # Внешне доступный URL этого бэкенда для callback-ов кнопок Mattermost.
    MATTERMOST_INTEGRATION_URL: Optional[str] = None
    # Служебный (read-only) аккаунт помощника Hermes.
    HERMES_BOT_EMAIL: str = "hermes-bot@system.local"
    HERMES_BOT_NAME: str = "Hermes (бот)"
    # Уровень структурного (JSON) логирования.
    LOG_LEVEL: str = "INFO"

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

        # If SSO is enabled, its credentials must be fully configured, otherwise
        # the login flow would 5xx on every attempt.
        if self.OIDC_ISSUER_URL and not (self.OIDC_CLIENT_ID and self.OIDC_CLIENT_SECRET):
            errors.append(
                "OIDC_ISSUER_URL is set, so OIDC_CLIENT_ID and OIDC_CLIENT_SECRET "
                "must also be provided to enable SSO."
            )

        if errors:
            raise RuntimeError(
                "Небезопасная конфигурация для production:\n  - " + "\n  - ".join(errors)
            )


settings = Settings()
