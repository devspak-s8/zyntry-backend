"""Small, provider-aware validation helpers for runtime model settings.

The API intentionally permits provider-specific/custom model identifiers.  We
only reject a value when its name unambiguously belongs to another provider;
unknown identifiers are left alone so private deployments and newly released
models continue to work.
"""

from __future__ import annotations


_MODEL_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("google", ("gemini", "gemma")),
    ("openai", ("gpt-", "o1", "o3", "o4", "chatgpt")),
    ("anthropic", ("claude",)),
    ("deepseek", ("deepseek",)),
    ("mistral", ("mistral", "mixtral", "codestral", "pixtral")),
    ("meta", ("llama", "meta-llama")),
    ("bedrock", ("anthropic.", "amazon.", "meta.", "mistral.")),
)

# These providers route to multiple upstream model families, so a model name
# alone is not enough to prove a mismatch.
_AGGREGATORS = {"groq", "openrouter"}


def infer_provider_for_model(model: str | None) -> str | None:
    """Infer a provider only for an unmistakable model-name family."""

    if not model:
        return None
    normalized = model.strip().lower()
    if not normalized:
        return None
    for provider, prefixes in _MODEL_PREFIXES:
        if normalized.startswith(prefixes):
            return provider
    return None


def provider_model_mismatch(provider: str | None, model: str | None) -> str | None:
    """Return a readable mismatch explanation, or ``None`` when compatible."""

    if not provider or not model:
        return None
    normalized_provider = provider.strip().lower()
    if normalized_provider in _AGGREGATORS:
        return None
    inferred = infer_provider_for_model(model)
    if inferred is None or inferred == normalized_provider:
        return None
    return (
        f"Model '{model}' belongs to provider '{inferred}', but provider "
        f"'{provider}' is configured. Choose a compatible {provider} model "
        "or change the provider and model together."
    )
