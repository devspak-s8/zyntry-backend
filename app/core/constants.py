from __future__ import annotations

DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

SERVICE_NAME: str = "zyntra"
API_TITLE: str = "Zyntra API"

TOKEN_TYPE_ACCESS: str = "access"
TOKEN_TYPE_REFRESH: str = "refresh"

PROVIDER_OPENAI: str = "openai"
PROVIDER_ANTHROPIC: str = "anthropic"
PROVIDER_GOOGLE: str = "google"
PROVIDER_DEEPSEEK: str = "deepseek"
PROVIDER_OPENROUTER: str = "openrouter"
PROVIDER_GROQ: str = "groq"
PROVIDER_MISTRAL: str = "mistral"
PROVIDER_COHERE: str = "cohere"
PROVIDER_VOYAGE: str = "voyage"
PROVIDER_FIREWORKS: str = "fireworks"
PROVIDER_AZURE: str = "azure"
PROVIDER_BEDROCK: str = "bedrock"

SUPPORTED_PROVIDERS: tuple[str, ...] = (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_DEEPSEEK,
    PROVIDER_OPENROUTER,
    PROVIDER_GROQ,
    PROVIDER_MISTRAL,
    PROVIDER_COHERE,
    PROVIDER_VOYAGE,
    PROVIDER_FIREWORKS,
    PROVIDER_AZURE,
    PROVIDER_BEDROCK,
)
