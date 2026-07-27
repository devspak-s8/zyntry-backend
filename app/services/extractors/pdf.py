from __future__ import annotations

from typing import Any

from pypdf import PdfReader

from app.extractors.base import BaseExtractor, ExtractedDocument, Heading, Paragraph, Table


class PdfExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        metadata: dict[str, Any] = {
            "pages": 0,
            "producer": None,
            "creator": None,
            "is_encrypted": False,
        }
        title = ""
        author = ""
        headings: list[Heading] = []
        paragraphs: list[Paragraph] = []
        tables: list[Table] = []

        try:
            reader = PdfReader(file_bytes)
            metadata["pages"] = len(reader.pages)
            metadata["is_encrypted"] = reader.is_encrypted

            info = reader.metadata
            if info:
                keys = {k.lower(): k for k in dir(info)}
                if "title" in keys and getattr(info, keys["title"]):
                    title = getattr(info, keys["title"])
                if "author" in keys and getattr(info, keys["author"]):
                    author = getattr(info, keys["author"])
                if "producer" in keys and getattr(info, keys["producer"]):
                    metadata["producer"] = getattr(info, keys["producer"])
                if "creator" in keys and getattr(info, keys["creator"]):
                    metadata["creator"] = getattr(info, keys["creator"])

            for page_index, page in enumerate(reader.pages, start=1):
                try:
                    if hasattr(page, "extract_text"):
                        text = page.extract_text() or ""
                    else:
                        text = ""
                except Exception:
                    text = ""

                text = text.strip()
                if not text:
                    continue

                lines = text.splitlines()
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue

                    is_heading = self._looks_like_heading(line)
                    if is_heading:
                        headings.append(
                            Heading(
                                level=is_heading,
                                text=stripped,
                            )
                        )
                    else:
                        paragraphs.append(Paragraph(text=stripped))

                try:
                    extracted_tables = page.extract_tables(
                        settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
                    )
                except Exception:
                    extracted_tables = []

                for raw_table in extracted_tables:
                    if not raw_table:
                        continue
                    sanitized = self._sanitize_table(raw_table)
                    if sanitized:
                        headers = sanitized[0] if sanitized else []
                        rows = sanitized[1:] if len(sanitized) > 1 else []
                        if headers or rows:
                            tables.append(
                                Table(
                                    headers=headers,
                                    rows=rows,
                                    caption=f"Page {page_index}",
                                )
                            )

            if not title and headings:
                title = headings[0].text
            if not title:
                title = self._infer_title(filename, paragraphs)

        except Exception:
            title = self._infer_title(filename, paragraphs)

        return ExtractedDocument(
            title=title,
            author=author if author else None,
            headings=headings,
            paragraphs=paragraphs,
            tables=tables,
            metadata=metadata,
            source=filename,
            hash=doc_hash,
        )

    @staticmethod
    def _looks_like_heading(line: str) -> int | None:
        stripped = line.strip()
        if not stripped:
            return None
        if len(stripped) > 200:
            return None
        if any(c in stripped for c in [":", ";", ".", ",", "!"]):
            return None
        if stripped.isupper() and len(stripped.split()) <= 10:
            return 1
        if stripped[0].isdigit() and stripped[:3].strip().endswith("."):
            return 2
        if 1 <= len(stripped.split()) <= 12 and len(stripped) < 120:
            pass
        if stripped.startswith(("CHAPTER", "Chapter")):
            return 1
        return None

    @staticmethod
    def _infer_title(filename: str, paragraphs: list[Paragraph]) -> str:
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        if paragraphs:
            return paragraphs[0].text[:120]
        return stem.replace("_", " ").replace("-", " ").strip() or filename

    @staticmethod
    def _sanitize_table(raw: list[list[Any]]) -> list[list[str]]:
        result: list[list[str]] = []
        for row in raw:
            sanitized = [str(cell).strip() if cell is not None else "" for cell in row]
            if any(sanitized):
                result.append(sanitized)
        return result
