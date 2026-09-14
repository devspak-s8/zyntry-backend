from app.services.model_providers.base import ModelInfo
from app.services.model_router import ModelRouter


def model(identifier: str, *, embeddings: bool = False) -> ModelInfo:
    return ModelInfo(
        id=identifier,
        name=identifier,
        provider="groq",
        max_context=128_000,
        supports_vision=False,
        supports_tools=True,
        supports_streaming=True,
        max_output_tokens=1024,
        supports_embeddings=embeddings,
    )


def test_automatic_routing_excludes_non_generation_models() -> None:
    assert not ModelRouter._is_generation_model(model("text-embedding-ada-002"))
    assert not ModelRouter._is_generation_model(model("meta-llama/llama-prompt-guard-2-86m"))
    assert not ModelRouter._is_generation_model(model("openai/gpt-oss-safeguard-20b"))
    assert not ModelRouter._is_generation_model(model("reranker-v2"))


def test_automatic_routing_keeps_chat_models() -> None:
    assert ModelRouter._is_generation_model(model("llama-3.3-70b-versatile"))
    assert ModelRouter._is_generation_model(model("groq/compound-mini"))
    assert not ModelRouter._is_generation_model(model("custom-chat", embeddings=True))
