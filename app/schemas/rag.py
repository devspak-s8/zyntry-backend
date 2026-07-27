from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: str
    section: str | None = None
    page: int | None = None
    source: str
    text_snippet: str


class SourceDocument(BaseModel):
    id: str
    title: str
    source: str
    page: int | None = None
    relevance_score: float


class RAGQuery(BaseModel):
    question: str
    project_id: str
    runtime_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict | None = None
    stream: bool = False
    conversation_id: str | None = None


class RAGResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sources: list[SourceDocument] = Field(default_factory=list)
    latency_ms: float = 0.0
    tokens_used: int = 0
    model: str = ""
