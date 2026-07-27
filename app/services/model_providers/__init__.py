from app.services.model_providers.base import BaseModelProvider
from app.services.model_providers.openai import OpenAIProvider
from app.services.model_providers.anthropic import AnthropicProvider
from app.services.model_providers.google import GoogleProvider
from app.services.model_providers.deepseek import DeepSeekProvider
from app.services.model_providers.groq import GroqProvider
from app.services.model_providers.openrouter import OpenRouterProvider
from app.services.model_providers.mistral import MistralProvider
from app.services.model_providers.meta import MetaProvider
from app.services.model_providers.bedrock import BedrockProvider

PROVIDER_REGISTRY: dict[str, type[BaseModelProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "deepseek": DeepSeekProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "mistral": MistralProvider,
    "meta": MetaProvider,
    "bedrock": BedrockProvider,
}