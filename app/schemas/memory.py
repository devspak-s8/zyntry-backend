from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    SESSION = "session"
    CONVERSATION = "conversation"
    LONG_TERM = "long_term"
    PROJECT = "project"


class MemoryRecordCreate(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    value: dict[str, Any] = Field(default_factory=dict)
    content: str | None = None
    memory_type: str = Field(default="long_term", max_length=32)
    project_id: str
    user_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    ttl: int | None = None
    pinned: bool = False


class MemoryRecordUpdate(BaseModel):
    value: dict[str, Any] | None = None
    content: str | None = None
    memory_type: str | None = Field(default=None, max_length=32)
    pinned: bool | None = None
    ttl: int | None = None


class MemoryRecordRead(BaseModel):
    id: str
    key: str
    value: dict[str, Any]
    content: str | None
    memory_type: str
    project_id: str
    user_id: str | None
    conversation_id: str | None
    session_id: str | None
    pinned: bool
    expires_at: datetime | None
    parent_key: str | None
    created_at: datetime
    updated_at: datetime


class MemoryToggleRequest(BaseModel):
    project_id: str
    enabled: bool


class MemorySearchParams(BaseModel):
    query: str
    project_id: str
    user_id: str | None = None
    memory_type: str | None = None
    limit: int = 10


class MemoryListParams(BaseModel):
    project_id: str
    user_id: str | None = None
    memory_type: str | None = None
    limit: int = 50


class MemoryDeleteRequest(BaseModel):
    project_id: str
    key: str
    user_id: str | None = None


class MemorySummaryResponse(BaseModel):
    id: str
    key: str
    content: str | None
    memory_type: str
    project_id: str
    user_id: str | None
    conversation_id: str | None
    session_id: str | None
    message_count: int | None = None
    parent_key: str | None
    created_at: datetime
    updated_at: datetime
