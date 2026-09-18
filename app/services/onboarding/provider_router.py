"""Provider-neutral model routing for onboarding.

Onboarding must not be coupled to one model vendor.  This module keeps the
provider adapters behind one small interface and uses the same health/failover
state as runtime request routing.  It never supplies a scripted answer: when
all configured providers fail, the caller receives the provider error and can
return the normal retryable onboarding response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, cast

import httpx

from app.core.config import settings
from app.services.model_providers import PROVIDER_REGISTRY
from app.services.model_registry import get_registered_model, list_registered_models
from app.services.onboarding.telemetry import current_trace
from app.services.provider_health import ProviderHealth, provider_health
from app.services.rag import BaseLLMProvider


@dataclass(frozen=True, slots=True)
class OnboardingProviderCandidate:
    provider: str
    model: str
    api_key: str


_SESSION_PROVIDER_COOLDOWNS: dict[tuple[str, str], float] = {}


def _session_provider_key(provider: str) -> tuple[str, str] | None:
    trace = current_trace()
    if trace is None or trace.session_id is None:
        return None
    return str(trace.session_id), provider


def _provider_is_session_cooled_down(provider: str) -> bool:
    key = _session_provider_key(provider)
    if key is None:
        return False
    now = time.monotonic()
    expiry = _SESSION_PROVIDER_COOLDOWNS.get(key)
    if expiry is None:
        return False
    if expiry <= now:
        _SESSION_PROVIDER_COOLDOWNS.pop(key, None)
        return False
    return True


def _cool_down_provider_for_session(provider: str) -> None:
    key = _session_provider_key(provider)
    if key is None:
        return
    try:
        seconds = max(1, int(getattr(settings, "ONBOARDING_PROVIDER_COOLDOWN_SECONDS", 30)))
    except (TypeError, ValueError):
        seconds = 30
    _SESSION_PROVIDER_COOLDOWNS[key] = time.monotonic() + seconds


class _GenericLLMAdapter(BaseLLMProvider):
    """Adapt the shared provider registry to the onboarding LLM interface."""

    def __init__(self, provider: str, api_key: str) -> None:
        self.provider = provider
        self.api_key = api_key
        self.last_status_code: int | None = None
        self.last_finish_reason: str | None = None
        self.last_response_schema_applied = False
        self.last_schema_has_refs = False

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        response_schema: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        provider_cls = PROVIDER_REGISTRY.get(self.provider)
        if provider_cls is None:
            raise RuntimeError(f"Unsupported onboarding provider: {self.provider}")
        provider_instance = provider_cls()
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # OpenRouter is OpenAI-compatible, but only its adapter knows how to
        # translate our provider-neutral schema into strict response_format.
        if response_schema is not None and self.provider == "openrouter":
            kwargs["response_schema"] = response_schema
        try:
            result = await provider_instance.chat_completion(**kwargs)
        finally:
            self.last_status_code = getattr(provider_instance, "last_status_code", None)
            self.last_finish_reason = getattr(provider_instance, "last_finish_reason", None)
            self.last_response_schema_applied = bool(
                getattr(provider_instance, "last_response_schema_applied", False)
            )
            self.last_schema_has_refs = bool(
                getattr(provider_instance, "last_schema_has_refs", False)
            )
        usage = getattr(result, "usage", {}) or {}
        total = usage.get("total_tokens")
        if total is None:
            total = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        return str(result), int(total or 0)

    async def astream(self, messages, model, max_tokens=2048, temperature=0.7, on_usage=None):
        # Onboarding currently persists complete assistant turns.  The method
        # is still implemented to satisfy BaseLLMProvider and keep the adapter
        # usable when onboarding streaming is introduced.
        result, _ = await self.generate(messages, model, max_tokens, temperature)
        yield result


class RoutedOnboardingLLMProvider(BaseLLMProvider):
    """Try configured onboarding providers in a health-aware order."""

    def __init__(
        self,
        candidates: list[OnboardingProviderCandidate],
        health: ProviderHealth | None = None,
    ) -> None:
        self.candidates = candidates
        self.health = health or provider_health
        self.last_provider: str | None = None
        self.last_model: str | None = None
        self.last_status_code: int | None = None
        self.last_finish_reason: str | None = None
        self.last_response_schema_applied = False
        self.last_schema_has_refs = False
        self.last_error_metadata: dict[str, str] = {}
        self.last_attempts: list[dict[str, str]] = []
        configured_limit = getattr(settings, "ONBOARDING_MAX_PROVIDER_ATTEMPTS", 2)
        try:
            self.max_attempts = max(1, int(configured_limit))
        except (TypeError, ValueError):
            self.max_attempts = 2

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        response_schema: dict | None = None,
    ) -> tuple[str, int]:
        self.last_attempts = []
        self.last_provider = None
        self.last_model = None
        self.last_status_code = None
        self.last_finish_reason = None
        self.last_response_schema_applied = False
        self.last_schema_has_refs = False
        self.last_error_metadata = {}
        errors: list[tuple[Exception, str, str, int | None, dict[str, str]]] = []
        attempts_started = 0
        for candidate in self.candidates:
            if _provider_is_session_cooled_down(candidate.provider):
                continue
            if not await self.health.is_available_async(candidate.provider):
                trace = current_trace()
                if trace:
                    attempt_id = trace.start_attempt(
                        operation="provider_routing",
                        provider=candidate.provider,
                        model=candidate.model or model,
                        attempt_number=attempts_started + 1,
                        status="cooldown",
                    )
                    trace.finish_attempt(attempt_id, status="skipped")
                continue
            if attempts_started >= self.max_attempts:
                break
            attempts_started += 1
            attempt_number = attempts_started
            selected_model = candidate.model or model
            self.last_attempts.append({
                "provider": candidate.provider,
                "model": selected_model,
                "status": "started",
            })
            trace = current_trace()
            active_attempt_id = (
                trace.start_attempt(
                    operation="provider_routing",
                    provider=candidate.provider,
                    model=selected_model,
                    attempt_number=attempt_number,
                )
                if trace
                else None
            )
            try:
                adapter: Any | None = None
                adapter = _adapter_for(candidate.provider, candidate.api_key)
                # Preserve the selected provider/model even when the adapter
                # fails. Telemetry for a failed call must not be reported as
                # ``unknown`` when routing already selected a candidate.
                self.last_provider = candidate.provider
                self.last_model = selected_model
                if response_schema is not None and hasattr(adapter, "generate"):
                    # Provider adapters translate the provider-neutral schema
                    # into their native structured-output format. Adapters
                    # that do not support the keyword retain the JSON-prompt
                    # compatibility path below.
                    try:
                        generate = cast(Any, adapter).generate
                        content, usage = await generate(
                            messages=messages,
                            model=selected_model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            response_schema=response_schema,
                        )
                    except TypeError as exc:
                        if "response_schema" not in str(exc):
                            raise
                        content, usage = await adapter.generate(
                            messages=messages,
                            model=selected_model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                        )
                else:
                    content, usage = await adapter.generate(
                        messages=messages,
                        model=selected_model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                await self.health.record_success_async(candidate.provider)
                self.last_status_code = getattr(adapter, "last_status_code", None)
                self.last_finish_reason = getattr(adapter, "last_finish_reason", None)
                self.last_response_schema_applied = bool(
                    getattr(adapter, "last_response_schema_applied", False)
                )
                self.last_schema_has_refs = bool(getattr(adapter, "last_schema_has_refs", False))
                self.last_error_metadata = {}
                self.last_attempts[-1]["status"] = "completed"
                if trace and active_attempt_id:
                    trace.finish_attempt(active_attempt_id, status="completed")
                return content, usage
            except Exception as exc:  # adapters expose provider-specific failures
                error_status = getattr(adapter, "last_status_code", None)
                error_metadata = getattr(adapter, "last_error_metadata", {})
                errors.append(
                    (
                        exc,
                        candidate.provider,
                        selected_model,
                        error_status,
                        error_metadata if isinstance(error_metadata, dict) else {},
                    )
                )
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    _cool_down_provider_for_session(candidate.provider)
                self.last_status_code = getattr(adapter, "last_status_code", None)
                self.last_finish_reason = getattr(adapter, "last_finish_reason", None)
                self.last_response_schema_applied = bool(
                    getattr(adapter, "last_response_schema_applied", False)
                )
                self.last_schema_has_refs = bool(getattr(adapter, "last_schema_has_refs", False))
                self.last_error_metadata = (
                    error_metadata if isinstance(error_metadata, dict) else {}
                )
                await self.health.record_failure_async(candidate.provider, type(exc).__name__)
                self.last_attempts[-1].update({"status": "failed", "error": type(exc).__name__})
                if trace and active_attempt_id:
                    trace.finish_attempt(active_attempt_id, status="failed", error=exc)

        if errors:
            # Only report rate limiting when every attempted provider was
            # rate-limited. If a fallback was attempted and failed for another
            # reason, report that final failure instead of blaming Gemini.
            non_rate_limit_errors = [
                item
                for item in errors
                if not (
                    isinstance(item[0], httpx.HTTPStatusError)
                    and item[0].response.status_code == 429
                )
            ]
            selected_error = non_rate_limit_errors[-1] if non_rate_limit_errors else errors[-1]
            self.last_provider = selected_error[1]
            self.last_model = selected_error[2]
            self.last_status_code = selected_error[3]
            self.last_error_metadata = selected_error[4]
            if non_rate_limit_errors:
                raise selected_error[0]
            raise selected_error[0]
        raise RuntimeError("No configured onboarding model provider is available")

    async def astream(self, messages, model, max_tokens=2048, temperature=0.7, on_usage=None):
        result, _ = await self.generate(messages, model, max_tokens, temperature)
        yield result


def _adapter_for(provider: str, api_key: str) -> BaseLLMProvider:
    normalized = provider.strip().lower()
    # These adapters preserve provider-specific system-message semantics.
    if normalized == "google":
        from app.services.onboarding.intelligence import GeminiLLMProvider

        return GeminiLLMProvider(api_key)
    if normalized == "openai":
        from app.services.rag import OpenAILLMProvider

        return OpenAILLMProvider(api_key)
    if normalized == "anthropic":
        from app.services.rag import AnthropicLLMProvider

        return AnthropicLLMProvider(api_key)
    return _GenericLLMAdapter(normalized, api_key)


_PROVIDER_KEYS: tuple[tuple[str, str], ...] = (
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
)

_DEFAULT_MODELS = {
    "google": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "deepseek": "deepseek-chat",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-large-latest",
}


def _model_for(provider: str, preferred_provider: str, configured_model: str) -> str:
    requested = configured_model.strip()
    if provider == "openrouter" and requested.lower() in {"", "auto", "automatic", "dynamic", "routing"}:
        configured_fallback = str(
            getattr(settings, "OPENROUTER_FALLBACK_MODEL", "openai/gpt-4o-mini")
            or "openai/gpt-4o-mini"
        ).strip()
        return configured_fallback or "openai/gpt-4o-mini"
    if requested and requested.lower() not in {"auto", "automatic", "dynamic", "routing"}:
        if provider == preferred_provider:
            return requested
        # A model identifier belongs to its provider.  Never send a Gemini
        # identifier to an OpenAI fallback, for example.
        if get_registered_model(provider, requested) is not None:
            return requested
    registered = list_registered_models(provider)
    generation = [item for item in registered if not item.supports_embeddings and item.max_output_tokens > 0]
    if generation:
        generation.sort(key=lambda item: (item.latency_tier != "low", item.input_price_per_1k or 999.0))
        return generation[0].id
    return _DEFAULT_MODELS.get(provider, requested or "")


def build_onboarding_provider() -> tuple[RoutedOnboardingLLMProvider | None, str]:
    """Build a routed provider from server-side credentials only.

    ``ONBOARDING_PROVIDER=auto`` (or ``routing``) tries all configured
    providers.  An explicit provider is preferred but other configured
    providers remain eligible for failover.  The returned model is a display
    value; each candidate carries its own compatible model identifier.
    """

    preferred = str(getattr(settings, "ONBOARDING_PROVIDER", "auto") or "auto").strip().lower()
    if preferred == "gemini":
        preferred = "google"
    configured_model = str(getattr(settings, "ONBOARDING_MODEL", "auto") or "auto")
    available: list[tuple[str, str]] = []
    for provider, setting_name in _PROVIDER_KEYS:
        key = str(getattr(settings, setting_name, "") or "").strip()
        if key:
            available.append((provider, key))
    if not available:
        return None, configured_model

    if preferred in {"auto", "automatic", "dynamic", "routing"}:
        order = [provider for provider, _ in _PROVIDER_KEYS]
    else:
        order = [preferred] + [provider for provider, _ in _PROVIDER_KEYS if provider != preferred]
    by_provider = dict(available)
    candidates = [
        OnboardingProviderCandidate(
            provider=provider,
            model=_model_for(provider, preferred, configured_model),
            api_key=by_provider[provider],
        )
        for provider in order
        if provider in by_provider and provider in PROVIDER_REGISTRY
    ]
    if not candidates:
        return None, configured_model
    return RoutedOnboardingLLMProvider(candidates), candidates[0].model
