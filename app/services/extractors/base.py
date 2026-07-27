from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel


class Heading(BaseModel):
    level: int
    text: str

    model_config = {"frozen": True}


class Paragraph(BaseModel):
    text: str
    metadata: dict[str, Any] = {}

    model_config = {"frozen": True}


class Table(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None

    model_config = {"frozen": True}


class ListItem(BaseModel):
    text: str
    ordered: bool = False

    model_config = {"frozen": True}


class CodeBlock(BaseModel):
    language: str | None
    code: str

    model_config = {"frozen": True}


class Link(BaseModel):
    text: str
    url: str | None = None

    model_config = {"frozen": True}


class ImageMeta(BaseModel):
    alt: str | None = None
    filename: str | None = None
    format: str | None = None
    width: int | None = None
    height: int | None = None

    model_config = {"frozen": True}


class ExtractedDocument(BaseModel):
    id: str | None = None
    title: str = ""
    author: str | None = None
    headings: list[Heading] = []
    paragraphs: list[Paragraph] = []
    tables: list[Table] = []
    lists: list[ListItem] = []
    metadata: dict[str, Any] = {}
    images: list[ImageMeta] = []
    code_blocks: list[CodeBlock] = []
    links: list[Link] = []
    source: str = ""
    language: str | None = None
    hash: str | None = None
    version: str | None = None

    model_config = {"frozen": False, "arbitrary_types_allowed": True}

    @property
    def content(self) -> str:
        parts: list[str] = []
        for heading in self.headings:
            parts.append((" " * (heading.level - 1)) + heading.text)
        for paragraph in self.paragraphs:
            parts.append(paragraph.text)
        for table in self.tables:
            parts.append(table.caption or "Table")
            parts.append("\t".join(table.headers))
            for row in table.rows:
                parts.append("\t".join(row))
        for item in self.lists:
            parts.append(("1. " if item.ordered else "- ") + item.text)
        for block in self.code_blocks:
            parts.append(f"```{block.language or ''}\n{block.code}\n```")
        return "\n\n".join(parts)

    def content_hash(self) -> str:
        raw = self.content.encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        raise NotImplementedError

    @staticmethod
    def _guess_extension(filename: str) -> str:
        suffix = PurePosixPath(filename).suffix.lower()
        return suffix.lstrip(".")

    @staticmethod
    def _hash_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
