from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key, hash_token
from app.models.apikeys import ApiKey
from app.repositories import UnitOfWork
from app.schemas.apikeys import ApiKeyRead


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.uow = UnitOfWork(session)

    async def rotate_key(self, api_key_id: str | uuid.UUID) -> dict:
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

        raw_key = generate_api_key("sk_live")
        new_key = await self.uow.api_keys.create(
            name=old_key.name,
            hashed_key=hash_token(raw_key),
            prefix=raw_key[:16],
            organization_id=old_key.organization_id,
            project_id=old_key.project_id,
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

    async def revoke_key(self, api_key_id: str | uuid.UUID) -> dict:
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
            "scopes": key.scopes,
            "revoked": key.revoked,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at,
            "usage_count": key.usage_count,
            "usage_stats": key.usage_stats,
            "created_at": key.created_at,
            "updated_at": key.updated_at,
        }

    async def list_keys(self, project_id: str | uuid.UUID | None = None) -> list[dict]:
        from sqlalchemy import select

        stmt = select(ApiKey)
        if project_id is not None:
            if isinstance(project_id, str):
                try:
                    pid = uuid.UUID(project_id)
                except ValueError:
                    raise ValueError("Invalid project id") from None
            else:
                pid = project_id
            stmt = stmt.where(ApiKey.project_id == pid)

        result = await self.session.execute(stmt)
        keys = result.scalars().all()

        return [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.prefix,
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

    async def get_usage(self, api_key_id: str | uuid.UUID) -> dict:
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

    async def update_scopes(self, api_key_id: str | uuid.UUID, scopes: list[str]) -> dict:
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
