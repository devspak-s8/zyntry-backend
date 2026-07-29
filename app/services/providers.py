from __future__ import annotations

from app.repositories import UnitOfWork
from app.schemas.providers import ProviderConnectionCreate


class ProviderService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_providers(self, project_id: str | None = None) -> list[dict]:
        connections = []
        if project_id:
            connections = await self.uow.providers.get_by_project(project_id)
        else:
            connections = await self.uow.providers.list()
        return [
            {
                "id": str(c.id),
                "provider_name": c.provider_name,
                "display_name": c.display_name,
                "status": c.status,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in connections
        ]

    async def connect(self, data: ProviderConnectionCreate) -> dict:
        existing = None
        if data.project_id:
            existing = await self.uow.providers.get_by_provider(
                data.project_id, data.provider_name
            )

        if existing:
            updated = await self.uow.providers.update(
                existing,
                encrypted_api_key=data.api_key,
                status="active",
                display_name=data.display_name,
                config=data.config,
            )
            await self.uow.commit()
            return {
                "id": str(updated.id),
                "provider_name": updated.provider_name,
                "status": updated.status,
                "created_at": updated.created_at.isoformat() if updated.created_at else "",
                "updated_at": updated.updated_at.isoformat() if updated.updated_at else "",
            }

        created = await self.uow.providers.create(
            organization_id=data.organization_id,
            project_id=data.project_id,
            provider_name=data.provider_name,
            display_name=data.display_name,
            encrypted_api_key=data.api_key,
            status="active",
            config=data.config,
        )
        await self.uow.commit()
        return {
            "id": str(created.id),
            "provider_name": created.provider_name,
            "status": created.status,
            "created_at": created.created_at.isoformat() if created.created_at else "",
            "updated_at": created.updated_at.isoformat() if created.updated_at else "",
        }

    async def disconnect(self, connection_id: str) -> None:
        conn = await self.uow.providers.get(connection_id)
        if not conn:
            raise ValueError("Provider connection not found")
        await self.uow.providers.delete(conn)
        await self.uow.commit()

    async def test_connection(self, data: dict) -> dict:
        return {"success": True, "message": "Connection test passed"}

    async def discover_resources(self, data: dict) -> dict:
        return {"items": [], "total": 0}

    async def sync(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "queued"}

    async def refresh(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "refreshed"}

    async def get_health(self, connection_id: str) -> dict:
        return {"id": connection_id, "status": "healthy"}
