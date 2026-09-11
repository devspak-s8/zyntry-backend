from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Zyntra"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    API_PREFIX: str = "/api"
    API_VERSION: str = "v1"

    # Security
    SECRET_KEY: str = ""
    ENCRYPTION_KEY: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ADMIN_JWT_ISSUER: str = "zyntra-admin"
    ADMIN_JWT_AUDIENCE: str = "zyntra-admin-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SESSION_TOKEN_TTL_MINUTES: int = 60
    PASSWORD_MIN_LENGTH: int = 8
    CSP_ENABLED: bool = True
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5173,http://zyntry.space,https://zyntry.space,https://app.zyntry.space,https://dashboard.zyntry.space"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://zyntra:zyntra@localhost:5432/zyntra"
    POSTGRES_USER: str = "zyntra"
    POSTGRES_PASSWORD: str = "zyntra"
    POSTGRES_DB: str = "zyntra"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    # Alembic owns production schema changes. This is an opt-in convenience
    # for local development when running the API without the entrypoint.
    AUTO_CREATE_TABLES: bool = False

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Vector
    VECTOR_PROVIDER: str = "pgvector"
    PGVECTOR_TABLE: str = "embeddings"

    # Providers
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    FIREWORKS_API_KEY: str = ""
    ONBOARDING_PROVIDER: str = "google"
    ONBOARDING_MODEL: str = "gemini-2.5-flash"
    RUNTIME_ASSISTANT_PROVIDER: str = "google"
    RUNTIME_ASSISTANT_MODEL: str = "gemini-2.5-flash"
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    BEDROCK_MODEL: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""

    # Email (SendByte)
    SENDBYTE_KEY: str = ""
    SENDBYTE_API_URL: str = "https://api.sendbyte.africa"
    EMAIL_ASSET_BASE_URL: str = "http://localhost:8000/static/email"

    # OAuth
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITLAB_CLIENT_ID: str = ""
    GITLAB_CLIENT_SECRET: str = ""
    BITBUCKET_CLIENT_ID: str = ""
    BITBUCKET_CLIENT_SECRET: str = ""
    NOTION_CLIENT_ID: str = ""
    NOTION_CLIENT_SECRET: str = ""
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = "common"
    JIRA_CLIENT_ID: str = ""
    JIRA_CLIENT_SECRET: str = ""
    CONFLUENCE_CLIENT_ID: str = ""
    CONFLUENCE_CLIENT_SECRET: str = ""
    ARCGIS_CLIENT_ID: str = ""
    ARCGIS_CLIENT_SECRET: str = ""

    # Billing
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_CREDITS: str = ""
    PADDLE_API_KEY: str = ""
    LEMON_SQUEEZY_API_KEY: str = ""
    BILLING_CURRENCY: str = "usd"
    BILLING_AUTO_TOP_UP_ENABLED: bool = True
    # Provider monitoring is safe by default; provider-side auto-recharge
    # remains an explicit per-account setting.
    PROVIDER_FUNDING_MONITOR_ENABLED: bool = True

    BACHS_API_KEY: str = ""
    BACHS_WEBHOOK_SECRET: str = ""
    BACHS_PRODUCT_ID: str = ""

    # GitHub App
    GITHUB_APP_ID: str = ""
    GITHUB_PRIVATE_KEY: str = ""

    # Monitoring
    PROMETHEUS_ENABLED: bool = False
    GRAFANA_ENABLED: bool = False

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_API_PER_MINUTE: int = 60
    RATE_LIMIT_LOGIN_MAX_ATTEMPTS: int = 5
    # Security-sensitive defaults fail closed when the shared limiter is
    # unavailable. Set true only for a deliberate availability trade-off.
    RATE_LIMIT_FAIL_OPEN: bool = False

    # Upload safety limits (enforced before document parsing)
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024
    ALLOWED_UPLOAD_EXTENSIONS: str = ".pdf,.docx,.txt,.md,.csv,.json"

    # Feature Flags
    ENABLE_MEMORY: bool = True
    ENABLE_RAG: bool = True
    ENABLE_ANALYTICS: bool = True
    ENABLE_TOOLS: bool = True
    ENABLE_ROUTER: bool = True

    # Admin Platform
    ADMIN_IP_ALLOWLIST: str = ""
    ADMIN_IP_BAN_CHECK: bool = True
    ADMIN_MFA_REQUIRED: bool = False
    ADMIN_SESSION_TTL_MINUTES: int = 60

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        """Return normalized browser origins from the single app config object."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def validate_startup(self) -> None:
        """Validate settings that must be present before serving application traffic.

        Keeping this policy beside the settings prevents the API lifespan,
        workers, and deployment scripts from gradually developing different
        production requirements.
        """
        if self.is_production and self.APP_DEBUG:
            raise RuntimeError("APP_DEBUG must be false when APP_ENV=production")
        if self.is_production or not self.APP_DEBUG:
            required = {
                "SECRET_KEY": self.SECRET_KEY,
                "JWT_SECRET": self.JWT_SECRET,
                "ENCRYPTION_KEY": self.ENCRYPTION_KEY,
                "DATABASE_URL": self.DATABASE_URL,
            }
            missing = [name for name, value in required.items() if not value]
            if self.DATABASE_URL == "postgresql+asyncpg://zyntra:zyntra@localhost:5432/zyntra":
                missing.append("DATABASE_URL")
            if missing:
                # Preserve order while avoiding duplicate DATABASE_URL entries.
                missing = list(dict.fromkeys(missing))
                raise RuntimeError(
                    "Missing required environment variables for production: "
                    + ", ".join(missing)
                )

    @model_validator(mode="after")
    def validate_environment(self) -> AppSettings:
        if self.is_production and self.APP_DEBUG:
            raise ValueError("APP_DEBUG must be false when APP_ENV=production")
        return self

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


settings = get_settings()
