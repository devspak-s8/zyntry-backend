"""Resolve model-provider credentials without exposing them to API clients.

Project credentials take precedence over organization credentials, which in
turn take precedence over the platform environment.  The database value is
encrypted for new connections; the small legacy fallback lets older
connections continue working while they are rotated.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.models.onboarding import ProviderConnection
from app.repositories import UnitOfWork
from app.services.model_providers import PROVIDER_REGISTRY
from app.services.security.secrets import default_secret_manager


PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "meta": "META_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}


def decrypt_provider_key(value: str | None) -> str | None:
    if not value:
        return None
    try:
        if value.startswith("ENCV1:"):
            return default_secret_manager.decrypt(value)
    except ValueError:
        return None
    # Connections created before encrypted_api_key was introduced contain a
    # legacy plaintext value.  Keep it usable but never return it in a read
    # response; new writes are always encrypted by ProviderService.
    return value


def environment_provider_key(provider_name: str) -> str | None:
    setting_name = PROVIDER_ENV_KEYS.get(provider_name.strip().lower())
    return getattr(settings, setting_name, None) if setting_name else None


async def _database_connection(
    uow: UnitOfWork,
    provider_name: str,
    *,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> ProviderConnection | None:
    provider_name = provider_name.strip().lower()
    if project_id:
        rows = await uow.providers.get_by_project(project_id)
        match = next(
            (
                row
                for row in rows
                if row.provider_name.strip().lower() == provider_name
                and row.is_active
                and row.status == "active"
            ),
            None,
        )
        if match:
            return match
    if organization_id:
        rows = await uow.providers.get_by_org(organization_id)
        return next(
            (
                row
                for row in rows
                if row.provider_name.strip().lower() == provider_name
                and row.is_active
                and row.status == "active"
            ),
            None,
        )
    return None


async def resolve_provider_key(
    uow: UnitOfWork,
    provider_name: str,
    *,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(credential, source)`` for a configured model provider."""
    normalized = provider_name.strip().lower()
    connection = await _database_connection(
        uow,
        normalized,
        project_id=project_id,
        organization_id=organization_id,
    )
    if connection:
        key = decrypt_provider_key(connection.encrypted_api_key)
        if key:
            return key, "project" if connection.project_id else "organization"
    key = environment_provider_key(normalized)
    return (key, "environment") if key else (None, None)


async def provider_credential_status(
    uow: UnitOfWork,
    provider_name: str,
    *,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> dict[str, Any]:
    normalized = provider_name.strip().lower()
    if normalized not in PROVIDER_REGISTRY:
        return {
            "provider": normalized,
            "valid": False,
            "reason": "unsupported_provider",
        }
    key, source = await resolve_provider_key(
        uow,
        normalized,
        project_id=project_id,
        organization_id=organization_id,
    )
    return {
        "provider": normalized,
        "valid": bool(key and key.strip()),
        "source": source,
        "reason": None if key and key.strip() else "missing_credentials",
    }
