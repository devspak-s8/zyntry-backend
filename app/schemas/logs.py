from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.organizations import ORMModel


class RequestLogRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    request_id: str
    method: str
    endpoint: str
    status: int
    latency_ms: int
    tokens: int | None
    provider: str | None
    model: str | None
    cost: int | None
    started_at: str | None
    completed_at: str | None
    user_id: uuid.UUID | None
    ip: str | None
    created_at: str
