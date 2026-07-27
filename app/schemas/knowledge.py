from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseRead(BaseModel):
    id: str
    name: str
    description: str | None
    project_id: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    content: str | None = None
    source: str | None = None
    knowledge_base_id: str


class DocumentRead(BaseModel):
    id: str
    title: str
    content: str | None
    source: str | None
    knowledge_base_id: str
    chunk_count: int
    author: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    language: str | None = None
    hash: str | None = None
    version: str | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeSourceCreate(BaseModel):
    project_id: str
    source_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    sync_frequency: str = Field(default="manual")
    connection_status: str = Field(default="pending")
    metadata: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None


class KnowledgeSourceRead(BaseModel):
    id: str
    project_id: str
    source_type: str
    display_name: str
    config: dict[str, Any]
    sync_frequency: str
    last_synced_at: str | None
    status: str
    is_active: bool
    connection_status: str
    last_error: str | None
    error_count: int
    sync_progress: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class KnowledgeSourceUpdate(BaseModel):
    display_name: str | None = None
    config: dict[str, Any] | None = None
    sync_frequency: str | None = None
    status: str | None = None
    is_active: bool | None = None
    connection_status: str | None = None
    metadata: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class SyncJobRead(BaseModel):
    id: str
    source_id: str
    project_id: str
    status: str
    progress: int
    current_step: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    stats: dict[str, Any]
    created_at: datetime
    updated_at: datetime
