from __future__ import annotations

import json
from typing import Any

from app.extractors.base import BaseExtractor, ExtractedDocument, Heading, ListItem, Paragraph, Table


class JsonExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        try:
            data = json.loads(file_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return ExtractedDocument(
                title=filename,
                source=filename,
                hash=doc_hash,
                metadata={"error": "invalid json"},
            )

        headings: list[Heading] = []
        paragraphs: list[Paragraph] = []
        lists: list[ListItem] = []
        tables: list[Table] = []
        metadata: dict[str, Any] = {}

        if isinstance(data, dict):
            top_keys = list(data.keys())
            for key in top_keys[:20]:
                headings.append(Heading(level=2, text=key))

            flat_texts = self._flatten(data)
            for text in flat_texts:
                paragraphs.append(Paragraph(text=text))

            for key, value in data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    table = self._list_of_dicts_to_table(value)
                    if table:
                        tables.append(table)

        elif isinstance(data, list):
            if data and isinstance(data[0], dict):
                table = self._list_of_dicts_to_table(data)
                if table:
                    tables.append(table)
            else:
                for item in data:
                    if isinstance(item, str):
                        paragraphs.append(Paragraph(text=item))
                    elif isinstance(item, (int, float, bool)):
                        paragraphs.append(Paragraph(text=str(item)))
                    elif isinstance(item, dict):
                        text = self._dict_to_text(item)
                        paragraphs.append(Paragraph(text=text))
                    elif item is None:
                        continue

        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        return ExtractedDocument(
            id=None,
            title=title,
            headings=headings,
            paragraphs=paragraphs,
            lists=lists,
            tables=tables,
            metadata=metadata,
            source=filename,
            hash=doc_hash,
        )

    @staticmethod
    def _flatten(obj: Any, prefix: str = "") -> list[str]:
        results: list[str] = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (str, int, float, bool)):
                    if prefix:
                        results.append(f"{prefix}.{key}: {value}")
                    else:
                        results.append(f"{key}: {value}")
                elif isinstance(value, list):
                    if value and isinstance(value[0], (str, int, float, bool)):
                        items = ", ".join(str(v) for v in value)
                        if prefix:
                            results.append(f"{prefix}.{key}: {items}")
                        else:
                            results.append(f"{key}: {items}")
                    else:
                        results.extend(
                            JsonExtractor._flatten(value, f"{prefix}.{key}" if prefix else key)
                        )
                elif isinstance(value, dict):
                    results.extend(
                        JsonExtractor._flatten(value, f"{prefix}.{key}" if prefix else key)
                    )
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                if isinstance(item, (str, int, float, bool)):
                    results.append(f"[{idx}]: {item}")
                else:
                    results.extend(
                        JsonExtractor._flatten(item, f"{prefix}[{idx}]")
                    )
        return results

    @staticmethod
    def _dict_to_text(obj: Any) -> str:
        if isinstance(obj, dict):
            parts = []
            for k, v in obj.items():
                parts.append(f"{k}: {v}")
            return ", ".join(parts)
        return str(obj)

    @staticmethod
    def _list_of_dicts_to_table(items: list[dict[str, Any]]) -> Table | None:
        if not items:
            return None
        headers = list(items[0].keys())
        rows: list[list[str]] = []
        for item in items:
            row = [str(item.get(h, "")) for h in headers]
            rows.append(row)
        return Table(headers=headers, rows=rows, caption=None)
