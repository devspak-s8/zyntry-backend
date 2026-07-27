from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.organizations import ORMModel


class ProviderConnectionCreate(BaseModel):
    provider: str
    api_key: str
    config: dict | None = None


class ProviderConnectionRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    api_key_last4: str | None
    is_active: bool
    created_at: str


class ModelRead(ORMModel):
    id: uuid.UUID
    name: str
    provider: str
    max_context: int
    supports_vision: bool
    supports_tools: bool
    input_price_per_1k: float | None
    output_price_per_1k: float | None
