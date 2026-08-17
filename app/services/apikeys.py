from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key, hash_token
from app.models.apikeys import ApiKey
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyCreate, ApiKeyRead


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.uow = UnitOfWork(session)

    async def create_key(
        self,
        user_id: uuid.UUID,
        data: ApiKeyCreate,
        organization_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        prefix_type = "sk_test" if data.environment in ("development", "staging", "test") else "sk_live"
        raw_key = generate_api_key(prefix_type)

        key = await self.uow.api_keys.create(
            name=data.name,
            hashed_key=hash_token(raw_key),
            prefix=raw_key[:16],
            user_id=user_id,
            runtime_id=data.runtime_id,
            project_id=data.project_id,
            organization_id=organization_id,
            environment=data.environment or "development",
            scopes=data.scopes or ["read", "write"],
            usage_count=0,
            usage_stats={},
        )
        await self.uow.commit()

        return {
            "api_key": ApiKeyRead(
                id=key.id,
                name=key.name,
                prefix=key.prefix,
                runtime_id=key.runtime_id,
                environment=key.environment,
                scopes=key.scopes,
                revoked=key.revoked,
                expires_at=key.expires_at,
                last_used_at=key.last_used_at,
                usage_count=key.usage_count,
                usage_stats=key.usage_stats,
                created_at=key.created_at,
                updated_at=key.updated_at,
            ),
            "raw_key": raw_key,
        }

    async def rotate_key(self, api_key_id: str | uuid.UUID) -> dict[str, Any]:
        if isinstance(api_key_id, str):
            try:
                kid = uuid.UUID(api_key_id)
            except ValueError:
                raise ValueError("Invalid api key id") from None
        else:
            kid = api_key_id

        old_key = await self.session.get(ApiKey, kid)
        if old_key is None:
            raise ValueError("API key not found")

        if old_key.revoked:
            raise ValueError("API key is already revoked")

        prefix_type = "sk_test" if getattr(old_key, "environment", "development") in ("development", "staging", "test") else "sk_live"
        raw_key = generate_api_key(prefix_type)
        new_key = await self.uow.api_keys.create(
            name=old_key.name,
            hashed_key=hash_token(raw_key),
            prefix=raw_key[:16],
            user_id=old_key.user_id,
            runtime_id=getattr(old_key, "runtime_id", None),
            project_id=old_key.project_id,
            organization_id=old_key.organization_id,
            environment=getattr(old_key, "environment", "development"),
            scopes=old_key.scopes,
            usage_count=0,
            usage_stats={},
        )

        await self.uow.api_keys.update(old_key, revoked=True)
        await self.uow.commit()

        return {
            "api_key": ApiKeyRead(
                id=new_key.id,
                name=new_key.name,
                prefix=new_key.prefix,
                runtime_id=new_key.runtime_id,
                environment=new_key.environment,
                scopes=new_key.scopes,
                revoked=new_key.revoked,
                expires_at=new_key.expires_at,
                last_used_at=new_key.last_used_at,
                usage_count=new_key.usage_count,
                usage_stats=new_key.usage_stats,
                created_at=new_key.created_at,
                updated_at=new_key.updated_at,
            ),
            "raw_key": raw_key,
        }

    async def revoke_key(self, api_key_id: str | uuid.UUID) -> dict[str, Any]:
        if isinstance(api_key_id, str):
            try:
                kid = uuid.UUID(api_key_id)
            except ValueError:
                raise ValueError("Invalid api key id") from None
        else:
            kid = api_key_id

        key = await self.session.get(ApiKey, kid)
        if key is None:
            raise ValueError("API key not found")

        await self.uow.api_keys.update(key, revoked=True)
        await self.uow.commit()

        return {
            "id": key.id,
            "name": key.name,
            "prefix": key.prefix,
            "runtime_id": getattr(key, "runtime_id", None),
            "environment": getattr(key, "environment", "development"),
            "scopes": key.scopes,
            "revoked": key.revoked,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at,
            "usage_count": key.usage_count,
            "usage_stats": key.usage_stats,
            "created_at": key.created_at,
            "updated_at": key.updated_at,
        }

    async def list_keys(
        self,
        project_id: str | uuid.UUID | None = None,
        user_id: str | uuid.UUID | None = None,
        runtime_id: str | uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(ApiKey)
        if project_id is not None:
            pid = uuid.UUID(str(project_id))
            stmt = stmt.where(ApiKey.project_id == pid)
        if user_id is not None:
            uid = uuid.UUID(str(user_id))
            stmt = stmt.where(ApiKey.user_id == uid)
        if runtime_id is not None:
            rid = uuid.UUID(str(runtime_id))
            stmt = stmt.where(ApiKey.runtime_id == rid)

        result = await self.session.execute(stmt)
        keys = result.scalars().all()

        return [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.prefix,
                "runtime_id": getattr(k, "runtime_id", None),
                "environment": getattr(k, "environment", "development"),
                "scopes": k.scopes,
                "revoked": k.revoked,
                "expires_at": k.expires_at,
                "last_used_at": k.last_used_at,
                "usage_count": k.usage_count,
                "usage_stats": k.usage_stats,
                "created_at": k.created_at,
                "updated_at": k.updated_at,
            }
            for k in keys
        ]

    async def get_usage(self, api_key_id: str | uuid.UUID) -> dict[str, Any]:
        if isinstance(api_key_id, str):
            try:
                kid = uuid.UUID(api_key_id)
            except ValueError:
                raise ValueError("Invalid api key id") from None
        else:
            kid = api_key_id

        key = await self.session.get(ApiKey, kid)
        if key is None:
            raise ValueError("API key not found")

        stats = key.usage_stats or {}
        return {
            "api_key_id": key.id,
            "calls": stats.get("calls", key.usage_count),
            "tokens": stats.get("tokens", 0),
            "errors": stats.get("errors", 0),
            "period_start": stats.get("period_start"),
            "period_end": stats.get("period_end"),
        }

    async def update_scopes(self, api_key_id: str | uuid.UUID, scopes: list[str]) -> dict[str, Any]:
        if isinstance(api_key_id, str):
            try:
                kid = uuid.UUID(api_key_id)
            except ValueError:
                raise ValueError("Invalid api key id") from None
        else:
            kid = api_key_id

        key = await self.session.get(ApiKey, kid)
        if key is None:
            raise ValueError("API key not found")

        await self.uow.api_keys.update(key, scopes=scopes)
        await self.uow.commit()

        return {
            "id": key.id,
            "name": key.name,
            "prefix": key.prefix,
            "runtime_id": getattr(key, "runtime_id", None),
            "environment": getattr(key, "environment", "development"),
            "scopes": key.scopes,
            "revoked": key.revoked,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at,
            "usage_count": key.usage_count,
            "usage_stats": key.usage_stats,
            "created_at": key.created_at,
            "updated_at": key.updated_at,
        }

    async def check_scope(self, api_key_id: str | uuid.UUID, scope: str) -> bool:
        if isinstance(api_key_id, str):
            try:
                kid = uuid.UUID(api_key_id)
            except ValueError:
                raise ValueError("Invalid api key id") from None
        else:
            kid = api_key_id

        key = await self.session.get(ApiKey, kid)
        if key is None:
            raise ValueError("API key not found")

        return scope in (key.scopes or [])
