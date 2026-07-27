from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Chunk:
    document_id: str | None
    section: str
    heading: str
    page: int
    source: str | None
    language: str | None
    hash: str
    version: str
    content: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


_CHARS_PER_TOKEN = 4
_DEFAULT_VERSION = "1"
_PAGE_SIZE = 2000


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _estimate_page(char_offset: int) -> int:
    return max(1, char_offset // _PAGE_SIZE + 1)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


def _chunk_semantic(text: str, chunk_size: int, overlap: int) -> list[str]:
    token_limit = chunk_size // _CHARS_PER_TOKEN
    sentences = _split_sentences(text)
    if not sentences:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        token_len = _estimate_tokens(sentence)
        if current and current_len + token_len > token_limit:
            chunk_text = " ".join(current)
            chunks.append(chunk_text)
            if overlap > 0:
                overlap_chars = 0
                keep: list[str] = []
                for s in reversed(current):
                    if overlap_chars + _estimate_tokens(s) <= overlap // _CHARS_PER_TOKEN:
                        keep.insert(0, s)
                        overlap_chars += _estimate_tokens(s)
                    else:
                        break
                current = keep
                current_len = sum(_estimate_tokens(s) for s in current)
            else:
                current = []
                current_len = 0
        current.append(sentence)
        current_len += token_len

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if c.strip()]


def _detect_language(text: str, source: str | None, language: str | None) -> str | None:
    if language:
        return language
    if source:
        ext = source.rsplit(".", 1)[-1].lower() if "." in source else ""
        lang_map = {
            "py": "python", "js": "javascript", "ts": "typescript",
            "java": "java", "go": "go", "rs": "rust", "rb": "ruby",
            "cpp": "cpp", "c": "c", "h": "c", "cs": "csharp",
            "php": "php", "swift": "swift", "kt": "kotlin",
            "scala": "scala", "sql": "sql", "sh": "bash",
            "yaml": "yaml", "yml": "yaml", "json": "json",
            "html": "html", "css": "css", "xml": "xml",
            "md": "markdown",
        }
        if ext in lang_map:
            return lang_map[ext]
    if text.startswith("#!"):
        shebang = text.split("\n")[0]
        if "python" in shebang:
            return "python"
        if "node" in shebang or "javascript" in shebang:
            return "javascript"
        if "bash" in shebang or "sh" in shebang:
            return "bash"
    return None


_CODE_BOUNDARY_PATTERNS = [
    re.compile(r'^(def |async def |class |function |export\s+(default\s+)?function|const\s+\w+\s*=\s*(async\s+)?\()', re.MULTILINE),
    re.compile(r'^(\s*)(def |async def |class |function )', re.MULTILINE),
]


def _is_code_boundary(line: str) -> bool:
    for pattern in _CODE_BOUNDARY_PATTERNS:
        if pattern.search(line):
            return True
    return False


_IMPORT_PATTERN = re.compile(r'^(import |from .+ import |require\(|#include )', re.MULTILINE)


def chunk_semantic(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []
    return _chunk_semantic(text, chunk_size, overlap)


def chunk_markdown(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []

    heading_pattern = re.compile(r'^(#{1,6}\s+.*)$', re.MULTILINE)
    code_block_pattern = re.compile(r'```[\s\S]*?```')
    lines = text.split("\n")

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    in_code_block = False
    code_buffer: list[str] = []

    for line in lines:
        if line.strip().startswith("```"):
            if in_code_block:
                code_buffer.append(line)
                current_lines.extend(code_buffer)
                code_buffer = []
                in_code_block = False
            else:
                if current_lines:
                    sections.append((current_heading, "\n".join(current_lines)))
                current_heading = ""
                current_lines = []
                code_buffer = [line]
                in_code_block = True
        elif in_code_block:
            code_buffer.append(line)
        elif heading_pattern.match(line):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines)))
            current_heading = line
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines or code_buffer:
        sections.append((current_heading, "\n".join(current_lines + code_buffer)))

    chunks: list[str] = []
    for heading, content in sections:
        if not content.strip():
            continue
        token_limit = chunk_size // _CHARS_PER_TOKEN
        if _estimate_tokens(content) <= token_limit:
            chunks.append(content)
        else:
            sub_chunks = _chunk_semantic(content, chunk_size, overlap)
            for sub in sub_chunks:
                chunks.append(sub)

    return [c for c in chunks if c.strip()]


def chunk_code(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []

    lines = text.split("\n")
    if not lines:
        return []

    chunks: list[str] = []
    boundaries: list[int] = [0]

    imports: list[str] = []
    import_done = False
    for i, line in enumerate(lines):
        if not import_done:
            if _IMPORT_PATTERN.match(line):
                imports.append(line)
                continue
            elif imports and line.strip() == "":
                import_done = True
                continue
            elif imports and not _IMPORT_PATTERN.match(line):
                import_done = True

        if _is_code_boundary(line):
            if i > 0 and boundaries[-1] != i:
                boundaries.append(i)

    boundaries.append(len(lines))

    i = 0
    while i < len(boundaries) - 1:
        start = boundaries[i]
        end = boundaries[i + 1]
        block = "\n".join(lines[start:end])
        if not block.strip():
            i += 1
            continue

        token_limit = chunk_size // _CHARS_PER_TOKEN
        if _estimate_tokens(block) <= token_limit:
            chunks.append(block)
        else:
            sub = _chunk_semantic(block, chunk_size, overlap)
            chunks.extend(sub)
        i += 1

    if not chunks and text.strip():
        chunks = _chunk_semantic(text, chunk_size, overlap)

    return [c for c in chunks if c.strip()]


def chunk_heading(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []

    heading_pattern = re.compile(r'^#{1,6}\s+.*$', re.MULTILINE)
    lines = text.split("\n")

    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        if heading_pattern.match(line):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines)))
            current_heading = line
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines)))

    chunks: list[str] = []
    token_limit = chunk_size // _CHARS_PER_TOKEN
    for heading, content in sections:
        if not content.strip():
            continue
        if _estimate_tokens(content) <= token_limit:
            chunks.append(content)
        else:
            sub = _chunk_semantic(content, chunk_size, overlap)
            chunks.extend(sub)

    return [c for c in chunks if c.strip()]


def chunk_sliding_window(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size - 1)

    chunks: list[str] = []
    start = 0
    char_size = chunk_size

    while start < len(text):
        end = start + char_size
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append(chunk_text)
        if end >= len(text):
            break
        start = end - overlap

    return chunks


def _detect_content_type(text: str, source: str | None) -> str:
    stripped = text.lstrip()
    if source:
        ext = source.rsplit(".", 1)[-1].lower() if "." in source else ""
        code_exts = {"py", "js", "ts", "java", "go", "rs", "rb", "cpp", "c",
                     "h", "cs", "php", "swift", "kt", "scala", "sql", "sh",
                     "yaml", "yml", "json", "html", "css", "xml", "toml"}
        if ext in code_exts:
            return "code"
        if ext == "md":
            return "markdown"

    if stripped.startswith("#"):
        return "markdown"
    if re.search(r'^(def |class |function |import |from |#include|package )', text, re.MULTILINE):
        return "code"
    if re.search(r'^(#{1,6}\s+)', text, re.MULTILINE):
        return "markdown"
    return "text"


def chunk_document(
    doc_content: str,
    chunk_size: int = 512,
    overlap: int = 64,
    strategy: str = "auto",
    language: str | None = None,
    source: str | None = None,
    document_id: str | None = None,
) -> list[Chunk]:
    if not doc_content or not doc_content.strip():
        return []

    content_type = None
    if strategy == "auto":
        content_type = _detect_content_type(doc_content, source)
        if content_type == "markdown":
            strategy = "markdown"
        elif content_type == "code":
            strategy = "code"
        else:
            strategy = "semantic"

    if strategy == "semantic":
        raw_chunks = chunk_semantic(doc_content, chunk_size, overlap)
    elif strategy == "markdown":
        raw_chunks = chunk_markdown(doc_content, chunk_size, overlap)
    elif strategy == "code":
        raw_chunks = chunk_code(doc_content, chunk_size, overlap)
    elif strategy == "heading":
        raw_chunks = chunk_heading(doc_content, chunk_size, overlap)
    elif strategy == "sliding_window":
        raw_chunks = chunk_sliding_window(doc_content, chunk_size, overlap)
    else:
        raw_chunks = chunk_semantic(doc_content, chunk_size, overlap)

    if not raw_chunks:
        return []

    detected_language = _detect_language(doc_content, source, language)
    chunks: list[Chunk] = []
    char_offset = 0

    for idx, chunk_text in enumerate(raw_chunks):
        heading = ""
        section = ""
        heading_match = re.search(r'^(#{1,6}\s+.*)$', chunk_text, re.MULTILINE)
        if heading_match:
            heading = heading_match.group(1).strip()
            section = heading.lstrip("#").strip()

        chunks.append(Chunk(
            document_id=document_id,
            section=section,
            heading=heading,
            page=_estimate_page(char_offset),
            source=source,
            language=detected_language,
            hash=_compute_hash(chunk_text),
            version=_DEFAULT_VERSION,
            content=chunk_text,
            chunk_index=idx,
            metadata={
                "strategy": strategy,
                "token_count": _estimate_tokens(chunk_text),
                "char_count": len(chunk_text),
            },
        ))
        char_offset += len(chunk_text)

    return chunks


def chunk_documents(
    docs: list[dict[str, Any]],
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for doc in docs:
        content = doc.get("content") or ""
        document_id = str(doc.get("id", "")) if doc.get("id") else None
        source = doc.get("source")
        language = doc.get("language")
        chunks = chunk_document(
            doc_content=content,
            chunk_size=chunk_size,
            overlap=overlap,
            strategy=doc.get("strategy", "auto"),
            language=language,
            source=source,
            document_id=document_id,
        )
        all_chunks.extend(chunks)
    return all_chunks


__all__ = [
    "Chunk",
    "chunk_document",
    "chunk_documents",
    "chunk_semantic",
    "chunk_markdown",
    "chunk_code",
    "chunk_heading",
    "chunk_sliding_window",
]
