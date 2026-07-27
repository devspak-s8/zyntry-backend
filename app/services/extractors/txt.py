from __future__ import annotations

import re

from app.extractors.base import BaseExtractor, ExtractedDocument, Paragraph


class TxtExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        raw = file_bytes.decode("utf-8", errors="replace")

        paragraphs: list[Paragraph] = []
        blocks = re.split(r"\n\s*\n", raw)
        for block in blocks:
            text = block.strip()
            if not text:
                continue
            paragraphs.append(Paragraph(text=text))

        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        return ExtractedDocument(
            id=None,
            title=title,
            paragraphs=paragraphs,
            source=filename,
            hash=doc_hash,
        )
