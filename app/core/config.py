from __future__ import annotations

from functools import lru_cache

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
    API_PREFIX: str = "/api"
    API_VERSION: str = "v1"

    # Security
    SECRET_KEY: str = ""
    ENCRYPTION_KEY: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SESSION_TOKEN_TTL_MINUTES: int = 10080
    PASSWORD_MIN_LENGTH: int = 8
    CSP_ENABLED: bool = True
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5173"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://zyntra:zyntra@localhost:5432/zyntra"
    POSTGRES_USER: str = "zyntra"
    POSTGRES_PASSWORD: str = "zyntra"
    POSTGRES_DB: str = "zyntra"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

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
    MISTRAL_API_KEY: str = ""
    COHERE_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""
    FIREWORKS_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    BEDROCK_MODEL: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""

    # Email (SendLib)
    SENDLIB_API_KEY: str = ""
    SENDLIB_API_URL: str = "https://sendlib.samueltuoyo.com"

    # OAuth
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""

    # Billing
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_CREDITS: str = ""
    PADDLE_API_KEY: str = ""
    LEMON_SQUEEZY_API_KEY: str = ""
    BILLING_CURRENCY: str = "usd"
    BILLING_AUTO_TOP_UP_ENABLED: bool = True

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

    # Feature Flags
    ENABLE_MEMORY: bool = True
    ENABLE_RAG: bool = True
    ENABLE_ANALYTICS: bool = True
    ENABLE_TOOLS: bool = True
    ENABLE_ROUTER: bool = True

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


settings = get_settings()
