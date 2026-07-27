from __future__ import annotations

import csv
import io
from typing import Any

from app.extractors.base import BaseExtractor, ExtractedDocument, Heading, Paragraph, Table


class CsvExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        raw = file_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(raw))
        rows: list[list[str]] = [row for row in reader if any(cell.strip() for cell in row)]

        if not rows:
            return ExtractedDocument(title=filename, source=filename, hash=doc_hash)

        headers = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []

        headings = [Heading(level=2, text=h) for h in headers if h.strip()]
        paragraphs: list[Paragraph] = [Paragraph(text=", ".join(headers))] if headers else []
        data = join_headers_with_rows(headers, data_rows)
        paragraphs.extend(data)

        table = Table(headers=headers, rows=data_rows, caption=None) if headers or data_rows else None
        tables = [table] if table else []

        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        return ExtractedDocument(
            id=None,
            title=title,
            headings=headings,
            paragraphs=paragraphs,
            tables=tables,
            source=filename,
            hash=doc_hash,
        )


def join_headers_with_rows(headers: list[str], rows: list[list[str]]) -> list[Paragraph]:
    result: list[Paragraph] = []
    for row in rows:
        parts = []
        for idx, header in enumerate(headers):
            value = row[idx] if idx < len(row) else ""
            if value:
                parts.append(f"{header}: {value}")
        if parts:
            result.append(Paragraph(text="\n".join(parts)))
        else:
            result.append(Paragraph(text=", ".join(row)))
    return result
