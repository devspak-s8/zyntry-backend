from __future__ import annotations

import io
import os
from typing import Any

from pypdf import PdfReader
from docx import Document as DocxDocument


SUPPORTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def detect_content_type(filename: str) -> str:
    _, ext = os.path.splitext(filename.lower())
    return SUPPORTED_EXTENSIONS.get(ext, "application/octet-stream")


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n\n".join(pages)


def extract_text_from_docx(data: bytes) -> str:
    document = DocxDocument(io.BytesIO(data))
    paragraphs: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text:
            paragraphs.append(paragraph.text)
    return "\n\n".join(paragraphs)


def extract_text(data: bytes, filename: str, content_type: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf") or content_type == "application/pdf":
        return extract_text_from_pdf(data)
    if lowered.endswith(".docx") or "wordprocessingml" in content_type:
        return extract_text_from_docx(data)
    if lowered.endswith(".txt") or lowered.endswith(".md") or content_type.startswith("text/"):
        return data.decode("utf-8", errors="ignore")
    return data.decode("utf-8", errors="ignore")


def build_metadata(filename: str, content_type: str, size: int) -> dict[str, Any]:
    return {
        "filename": filename,
        "content_type": content_type or detect_content_type(filename),
        "size": size,
    }
