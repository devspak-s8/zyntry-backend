from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_serializer(mode="wrap")
    def _serialize_model(self, handler):
        data = handler(self)
        return _convert_decimals(data)


def _convert_decimals(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_decimals(i) for i in obj]
    return obj


class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class OrganizationCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    region: str = "us-central1"
    created_at: datetime
