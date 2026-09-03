"""Safe parsing and validation for conversational runtime configuration changes.

The assistant may suggest a configuration change in natural language, but this
module keeps the mutation surface explicit.  Unknown fields and values are
rejected before a confirmation proposal is persisted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.schemas.runtimes import RuntimeUpdate


CONFIG_KEYS = frozenset(
    {
        "temperature",
        "max_tokens",
        "dynamic_routing_enabled",
        "cache_enabled",
        "cache_ttl_seconds",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
    }
)

UPDATE_FIELDS = frozenset(
    {
        "name",
        "environment",
        "provider",
        "model",
        "fallback_models",
        "routing_strategy",
        "embedding_model",
        "vector_store",
        "chunk_size",
        "chunk_overlap",
        "system_instructions",
        "security_policies",
        "config",
    }
)

# Changes to these fields alter the runtime artifact or its retrieval index.
# The assistant reports the impact and leaves the actual rebuild as a separate
# explicitly confirmed operation.
REBUILD_FIELDS = frozenset(
    {
        "provider",
        "model",
        "fallback_models",
        "routing_strategy",
        "embedding_model",
        "vector_store",
        "chunk_size",
        "chunk_overlap",
        "system_instructions",
    }
)

ENVIRONMENT_ALIASES = {
    "dev": "development",
    "development": "development",
    "stage": "staging",
    "staging": "staging",
    "prod": "production",
    "production": "production",
}

ROUTING_STRATEGIES = frozenset(
    {"latency_optimized", "quality_optimized", "balanced"}
)

_MUTATION_WORDS = r"(?:set|change|update|switch|make|use)"
_VALUE = r"([^\n,;]+?)(?=\s+and\s+(?:set|change|update|switch|make|use|rebuild)\b|$)"
_VALUE_LIST = r"([^\n;]+?)(?=\s+and\s+(?:set|change|update|switch|make|use|rebuild)\b|$)"


def _clean_text(value: Any, field: str, *, max_length: int = 255) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip().strip("\"'` ")
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field} is too long")
    return cleaned


def _number(value: Any, field: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        parsed = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    return parsed


def _boolean(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "enabled", "enable"}:
            return True
        if lowered in {"false", "no", "off", "disabled", "disable"}:
            return False
    raise ValueError(f"{field} must be true or false")


def _normalize_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping) or not config:
        raise ValueError("config must contain at least one supported setting")

    aliases = {
        "max_token": "max_tokens",
        "max_output_tokens": "max_tokens",
        "dynamic_routing": "dynamic_routing_enabled",
        "cache": "cache_enabled",
        "cache_ttl": "cache_ttl_seconds",
    }
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in config.items():
        key = aliases.get(str(raw_key).strip().lower(), str(raw_key).strip().lower())
        if key not in CONFIG_KEYS:
            raise ValueError(f"Unsupported runtime config setting: {raw_key}")
        if key == "temperature":
            value = _number(raw_value, key)
            if not 0 <= value <= 2:
                raise ValueError("temperature must be between 0 and 2")
        elif key == "max_tokens":
            value = _number(raw_value, key, integer=True)
            if not 1 <= value <= 100000:
                raise ValueError("max_tokens must be between 1 and 100000")
        elif key == "dynamic_routing_enabled":
            value = _boolean(raw_value, key)
        elif key == "cache_enabled":
            value = _boolean(raw_value, key)
        elif key == "cache_ttl_seconds":
            value = _number(raw_value, key, integer=True)
            if not 0 <= value <= 86400:
                raise ValueError("cache_ttl_seconds must be between 0 and 86400")
        else:
            value = _number(raw_value, key)
            if key == "top_p" and not 0 <= value <= 1:
                raise ValueError("top_p must be between 0 and 1")
            if key in {"frequency_penalty", "presence_penalty"} and not -2 <= value <= 2:
                raise ValueError(f"{key} must be between -2 and 2")
        normalized[key] = value
    return normalized


def normalize_configuration_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize a proposed RuntimeUpdate payload.

    The returned value is safe to store in an action proposal.  Runtime-owned
    identity and lifecycle fields (project, status, API keys, etc.) are not in
    the allowlist and therefore cannot be changed through this action.
    """

    if not isinstance(changes, Mapping) or not changes:
        raise ValueError("At least one runtime configuration change is required")

    payload: dict[str, Any] = {}
    config_updates: dict[str, Any] = {}
    for raw_key, raw_value in changes.items():
        key = str(raw_key).strip().lower()
        if key == "config":
            if not isinstance(raw_value, Mapping):
                raise ValueError("config must be an object")
            config_updates.update(_normalize_config(raw_value))
            continue
        if key not in UPDATE_FIELDS:
            raise ValueError(f"Unsupported runtime configuration field: {raw_key}")
        if key in {"name", "provider", "model", "embedding_model", "vector_store", "system_instructions"}:
            payload[key] = _clean_text(raw_value, key, max_length=20000 if key == "system_instructions" else 255)
        elif key == "environment":
            environment = _clean_text(raw_value, key).lower()
            if environment not in ENVIRONMENT_ALIASES:
                raise ValueError("environment must be development, staging, or production")
            payload[key] = ENVIRONMENT_ALIASES[environment]
        elif key == "routing_strategy":
            strategy = _clean_text(raw_value, key).lower().replace("-", "_").replace(" ", "_")
            # Automatic model routing is represented by the runtime's dynamic
            # routing flag. Keep the persisted routing strategy canonical
            # (latency/quality/balanced) while accepting the natural-language
            # setting users commonly ask for.
            if strategy in {"automatic", "automatic_model_routing", "dynamic", "dynamic_routing"}:
                config_updates["dynamic_routing_enabled"] = True
                continue
            if strategy not in ROUTING_STRATEGIES:
                raise ValueError("routing_strategy must be latency_optimized, quality_optimized, or balanced")
            payload[key] = strategy
        elif key in {"chunk_size", "chunk_overlap"}:
            parsed = _number(raw_value, key, integer=True)
            maximum = 4096 if key == "chunk_size" else 512
            minimum = 64 if key == "chunk_size" else 0
            if not minimum <= parsed <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
            payload[key] = parsed
        elif key == "fallback_models":
            values = raw_value.split(",") if isinstance(raw_value, str) else raw_value
            if not isinstance(values, (list, tuple)) or not values:
                raise ValueError("fallback_models must contain at least one model")
            payload[key] = [_clean_text(item, "fallback_models entry") for item in values]
        elif key == "security_policies":
            if not isinstance(raw_value, Mapping):
                raise ValueError("security_policies must be an object")
            payload[key] = dict(raw_value)

    if config_updates:
        payload["config"] = config_updates
    if not payload:
        raise ValueError("At least one runtime configuration change is required")

    # Reuse the public RuntimeUpdate schema for cross-field and future schema
    # validation, while deliberately excluding project_id from this action.
    RuntimeUpdate(**payload)
    if payload.get("chunk_overlap") is not None:
        chunk_size = payload.get("chunk_size", 512)
        if payload["chunk_overlap"] >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
    return payload


def parse_configuration_change(message: str) -> dict[str, Any] | None:
    """Extract one or more explicit setting changes from a user message.

    A read question such as "what is the configuration?" returns ``None``.
    This parser only returns a mutation when the user names both a setting and
    a requested value (or an explicit enable/disable operation).
    """

    text = " ".join(message.strip().split())
    lowered = text.lower()
    changes: dict[str, Any] = {}

    dynamic = re.search(
        r"\b(enable|disable|turn\s+on|turn\s+off|activate|deactivate)\s+(?:the\s+)?(?:dynamic\s+)?(?:model\s+)?routing\b",
        lowered,
    )
    if dynamic:
        changes["config"] = {"dynamic_routing_enabled": dynamic.group(1) in {"enable", "turn on", "activate"}}

    # Users often describe the same setting as "automatic model routing" or
    # "route the models automatically". Only accept it when paired with an
    # explicit change verb so a read question cannot become a mutation.
    # ``automatc``/``automtic`` are common keyboard slips in chat. They are
    # accepted only in this explicit mutation pattern; a read question still
    # returns ``None`` and cannot create a proposal.
    automatic_word = r"autom(?:atic|atc|tic)(?:ally)?"
    automatic_routing = re.search(
        rf"\b(?:enable|activate|change|configure|set|set\s+up|turn\s+on|make|switch\s+to)\b.*\b(?:{automatic_word}(?:\s+(?:model\s+)?routing|\s+route\s+(?:the\s+)?models?)?|route\s+(?:the\s+)?models?\s+{automatic_word}|dynamic(?:\s+model)?\s+routing)\b",
        lowered,
    )
    automatic_routing_disabled = re.search(
        rf"\b(?:disable|deactivate|turn\s+off|stop)\b.*\b(?:{automatic_word}(?:\s+(?:model\s+)?routing|\s+route\s+(?:the\s+)?models?)?|route\s+(?:the\s+)?models?\s+{automatic_word}|dynamic(?:\s+model)?\s+routing)\b",
        lowered,
    )
    if automatic_routing or automatic_routing_disabled:
        changes["config"] = {
            "dynamic_routing_enabled": automatic_routing_disabled is None,
        }

    # Follow-up messages commonly omit the noun because it is already clear
    # from the conversation (for example, “change it to automatic”). Treat
    # that explicit continuation as a routing change, never as a read query.
    contextual_automatic = re.search(
        rf"\b(?:change|switch|set|make)\s+(?:it|this|that)\s+to\s+(?:{automatic_word}|dynamic)\b",
        lowered,
    )
    if contextual_automatic:
        changes["config"] = {"dynamic_routing_enabled": True}

    def capture(pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return match.group(1).strip().strip("\"'`").rstrip(".").strip() if match else None

    provider = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?(?:default\s+)?(?:model\s+)?provider\s+(?:to|as|=)\s*{_VALUE}")
    if not provider:
        provider_match = re.search(r"\b(?:use|switch\s+to)\s+([^\n,;]+?)\s+as\s+(?:the\s+)?provider\b", text, flags=re.IGNORECASE)
        provider = provider_match.group(1).strip().strip("\"'`").rstrip(".").strip() if provider_match else None
    if provider:
        changes["provider"] = provider
    model = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?(?:default\s+)?model\s+(?:to|as|=)\s*{_VALUE}")
    if not model:
        model_match = re.search(r"\b(?:use|switch\s+to)\s+([^\n,;]+?)\s+as\s+(?:the\s+)?model\b", text, flags=re.IGNORECASE)
        model = model_match.group(1).strip().strip("\"'`").rstrip(".").strip() if model_match else None
    if model:
        changes["model"] = model
    temperature = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?temperature\s+(?:to|=)\s*(-?\d+(?:\.\d+)?)")
    if temperature:
        changes.setdefault("config", {})["temperature"] = temperature
    max_tokens = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?(?:maximum\s+)?tokens?\s+(?:to|=)\s*(\d+)")
    if max_tokens:
        changes.setdefault("config", {})["max_tokens"] = max_tokens
    dynamic_value = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?(?:dynamic\s+)?routing\s+(?:to|as|=)\s*(true|false|on|off|enabled|disabled)")
    if dynamic_value:
        changes.setdefault("config", {})["dynamic_routing_enabled"] = dynamic_value
    cache_ttl = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?cache\s+ttl(?:\s+seconds?)?\s+(?:to|=)\s*(\d+)")
    if cache_ttl:
        changes.setdefault("config", {})["cache_ttl_seconds"] = cache_ttl
    top_p = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?top[_\s-]?p\s+(?:to|=)\s*(-?\d+(?:\.\d+)?)")
    if top_p:
        changes.setdefault("config", {})["top_p"] = top_p
    for config_key, label in (("frequency_penalty", r"frequency[_\s-]?penalty"), ("presence_penalty", r"presence[_\s-]?penalty")):
        penalty = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?{label}\s+(?:to|=)\s*(-?\d+(?:\.\d+)?)")
        if penalty:
            changes.setdefault("config", {})[config_key] = penalty
    environment = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?environment\s+(?:to|as|=)\s*{_VALUE}")
    if environment:
        changes["environment"] = environment
    routing = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?routing\s+strategy\s+(?:to|as|=)\s*{_VALUE}")
    if routing:
        changes["routing_strategy"] = routing
    embedding = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?embedding\s+model\s+(?:to|as|=)\s*{_VALUE}")
    if embedding:
        changes["embedding_model"] = embedding
    vector_store = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?vector\s+store\s+(?:to|as|=)\s*{_VALUE}")
    if vector_store:
        changes["vector_store"] = vector_store
    chunk_size = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?chunk\s+size\s+(?:to|=)\s*(\d+)")
    if chunk_size:
        changes["chunk_size"] = chunk_size
    chunk_overlap = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?chunk\s+overlap\s+(?:to|=)\s*(\d+)")
    if chunk_overlap:
        changes["chunk_overlap"] = chunk_overlap
    fallback_models = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?fallback\s+models?\s+(?:to|as|=)\s*{_VALUE_LIST}")
    if fallback_models:
        changes["fallback_models"] = [item.strip() for item in fallback_models.split(",")]
    name = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?(?:runtime\s+)?name\s+(?:to|as|=)\s*{_VALUE}")
    if name:
        changes["name"] = name
    instructions = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?system\s+instructions?\s+(?:to|as|=)\s*(.+)$")
    if instructions:
        changes["system_instructions"] = instructions

    cache_toggle = re.search(
        r"\b(enable|disable|turn\s+on|turn\s+off)\s+(?:the\s+)?cache\b",
        lowered,
    )
    if cache_toggle:
        changes.setdefault("config", {})["cache_enabled"] = cache_toggle.group(1) in {"enable", "turn on"}
    cache_value = capture(rf"\b{_MUTATION_WORDS}\s+(?:the\s+)?cache\s+(?:enabled|active)\s+(?:to|as|=)\s*(true|false|on|off|enabled|disabled)")
    if cache_value:
        changes.setdefault("config", {})["cache_enabled"] = cache_value

    if not changes:
        return None
    return normalize_configuration_changes(changes)


def configuration_change_impact(changes: Mapping[str, Any]) -> dict[str, Any]:
    """Return user-facing impact details for a normalized change set."""

    changed_fields: list[str] = []
    for key, value in changes.items():
        if key == "config":
            changed_fields.extend(f"config.{nested}" for nested in value)
        else:
            changed_fields.append(key)
    rebuild_fields = [field for field in changed_fields if field in REBUILD_FIELDS]
    return {
        "changed_fields": changed_fields,
        "requires_rebuild": bool(rebuild_fields),
        "rebuild_fields": rebuild_fields,
    }
