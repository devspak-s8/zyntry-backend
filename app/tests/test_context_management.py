from app.services.context_manager import ContextManager
from app.services.model_providers.base import ProviderResponse
from app.services.model_registry import get_registered_model, list_registered_models
from app.services.provider_health import ProviderHealth
from app.services.token_engine import TokenEngine


def test_registry_contains_context_and_capability_metadata():
    gemini = get_registered_model("google", "gemini-2.5-flash")
    assert gemini is not None
    assert gemini.context_window >= 1_000_000
    assert gemini.max_output_tokens > 0
    assert gemini.supports_tools is True
    assert any(item.provider == "openai" for item in list_registered_models())


def test_context_manager_reserves_output_and_keeps_latest_request():
    manager = ContextManager()
    messages = [
        {"role": "system", "content": "Runtime rules"},
        {"role": "user", "content": "old context " * 600},
        {"role": "assistant", "content": "old answer " * 600},
        {"role": "user", "content": "current question"},
    ]
    assembly = manager.assemble(
        messages,
        provider="openai",
        model="gpt-3.5-turbo",
        requested_output_tokens=512,
        context_override=2_048,
    )
    assert assembly.messages[-1]["content"] == "current question"
    assert assembly.budget.reserved_output >= 512
    assert assembly.dropped_messages > 0 or assembly.compressed_messages > 0
    assert assembly.estimated_input_tokens <= assembly.budget.working_input


def test_token_engine_prefers_provider_usage_when_available():
    text, usage = TokenEngine.normalize_usage(
        {"content": "answer", "usage": {"prompt_tokens": 12, "completion_tokens": 7}},
        estimated_input_tokens=100,
        estimated_output_tokens=100,
    )
    assert text == "answer"
    assert usage.input_tokens == 12
    assert usage.output_tokens == 7
    assert usage.source == "provider"


def test_provider_response_remains_text_compatible_with_usage_metadata():
    response = ProviderResponse("answer", {"prompt_tokens": 8, "completion_tokens": 3})
    text, usage = TokenEngine.normalize_usage(
        response,
        estimated_input_tokens=100,
        estimated_output_tokens=100,
    )
    assert response == "answer"
    assert text == "answer"
    assert usage.total_tokens == 11


def test_context_manager_never_truncates_system_instructions():
    manager = ContextManager()
    system = "Do not bypass authorization. " * 400
    assembly = manager.assemble(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Answer this question."},
        ],
        provider="openai",
        model="gpt-3.5-turbo",
        requested_output_tokens=256,
        context_override=2_048,
    )
    assert assembly.messages[0]["content"] == system
    assert any("System context" in warning for warning in assembly.warnings)


def test_provider_health_enters_cooldown_after_repeated_failures():
    health = ProviderHealth(failure_threshold=2, cooldown_seconds=60)
    health.record_failure("openai", "timeout")
    assert health.is_available("openai")
    health.record_failure("openai", "rate limit")
    assert not health.is_available("openai")
    assert health.snapshot()[0]["last_error"] == "rate limit"
    health.record_success("openai", 12)
    assert health.is_available("openai")
