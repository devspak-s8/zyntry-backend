from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services.connectors.base import BaseConnector, ConnectorAuthError, ConnectorDiscoveryError, ConnectorNetworkError, ConnectorRateLimitError
from app.services.connectors import registry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class S3Connector(BaseConnector):
    async def connect(self) -> dict:
        self._status = {"status": "connected", "message": "S3 connected"}
        return self._status

    async def test(self) -> dict:
        # TODO: validate S3/R2/B2/Azure/GCS credentials and list bucket
        return {"success": True, "message": "S3 connection test stub"}

    async def discover(self) -> dict:
        # TODO: list S3 buckets/objects via object storage API
        return {"items": [], "total": 0}

    async def sync(self, options: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        # TODO: trigger S3 object indexing
        return {"job_id": job_id, "status": "running", "started_at": started_at}

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        # TODO: refresh S3/R2/B2/Azure/GCS credentials
        return {"success": True, "message": "Credentials refreshed stub"}

    def validate(self) -> dict:
        return {"valid": True, "errors": []}

    def watch(self, poll_interval: int = 120) -> Any:
        raise NotImplementedError("S3 watcher support has been removed. Use the sync() method instead.")


registry.register("s3", S3Connector)
