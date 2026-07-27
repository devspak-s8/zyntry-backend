from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Heading(BaseModel):
    level: int = Field(ge=1, le=6)
    text: str = Field(min_length=1)


class ListItem(BaseModel):
    text: str = Field(min_length=1)
    ordered: bool = False


class Table(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    caption: str | None = None


class CodeBlock(BaseModel):
    language: str | None = None
    code: str = ""


class Link(BaseModel):
    text: str = ""
    url: str | None = None


class ImageMeta(BaseModel):
    alt: str | None = None
    filename: str | None = None
    format: str | None = None
    width: int | None = None
    height: int | None = None


class ExtractedDocument(BaseModel):
    id: str | None = None
    title: str = Field(default="", max_length=512)
    author: str | None = None
    headings: list[Heading] = Field(default_factory=list)
    paragraphs: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    lists: list[ListItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    images: list[ImageMeta] = Field(default_factory=list)
    code_blocks: list[CodeBlock] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    source: str = Field(default="", max_length=512)
    language: str | None = None
    hash: str | None = None
    version: str | None = None


class DocumentExtract(BaseModel):
    id: str
    title: str
    content: str | None = None
    author: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    language: str | None = None
    hash: str | None = None
    version: str | None = None
    source: str | None = None
    chunk_count: int = 0


class DocumentExtractionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    data: str = Field(min_length=1)


class DocumentExtractionResponse(BaseModel):
    document: DocumentExtract
    extracted: ExtractedDocument


class FileUploadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    knowledge_base_id: str
    source: str | None = None
