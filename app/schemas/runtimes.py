from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.organizations import ORMModel


class RuntimeCreate(ORMModel):
    project_id: uuid.UUID
    organization_id: uuid.UUID
    provider: str = "openai"
    model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    vector_store: str = "pgvector"
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)
    config: dict = Field(default_factory=dict)


class RuntimeUpdate(ORMModel):
    provider: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    vector_store: str | None = None
    chunk_size: int | None = Field(default=None, ge=64, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=512)
    config: dict | None = None


class RuntimeRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    version: str
    provider: str
    model: str
    embedding_model: str
    vector_store: str
    chunk_size: int
    chunk_overlap: int
    documents: int
    chunks: int
    embeddings: int
    index_size: int
    last_build_started: datetime | None
    last_build_completed: datetime | None
    last_propagated: datetime | None
    health: float
    error_message: str | None
    api_key_id: uuid.UUID | None
    config: dict
    metadata: dict
    created_at: datetime
    updated_at: datetime


class RuntimeBuildLogRead(ORMModel):
    id: uuid.UUID
    runtime_id: uuid.UUID
    stage: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime


class RuntimeBuildChunkRead(ORMModel):
    id: uuid.UUID
    runtime_id: uuid.UUID
    document_id: uuid.UUID | None
    chunk_index: int
    action: str
    embedded: bool
    indexed: bool
    embedding_hash: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime


class RuntimeHealthResponse(ORMModel):
    status: str
    health: float
    version: str
    last_build: datetime | None
    last_propagation: datetime | None
    documents: int
    chunks: int
    embeddings: int
    index_size: int
    errors: int
    current_queue: str | None
    embedding_latency_ms: float | None = None
    retrieval_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    token_usage: int = 0
    storage_usage: int = 0
    memory_usage_mb: float | None = None
    worker_queue_depth: int = 0
    last_sync_success: str | None = None
    last_propagation_success: str | None = None
    health_score: float | None = None
    error_count: int = 0
    cache_hit_rate: float | None = None
    retrieval_quality: float | None = None
