from __future__ import annotations

import re
from typing import Any

bs4_spec = None
try:
    from bs4 import BeautifulSoup

    bs4_spec = BeautifulSoup
except Exception:
    pass

from app.extractors.base import BaseExtractor, CodeBlock, ExtractedDocument, Heading, Link, ListItem, Paragraph, Table


class HtmlExtractor(BaseExtractor):
    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        if bs4_spec is None:
            return ExtractedDocument(
                title=filename,
                source=filename,
                hash=doc_hash,
                metadata={"error": "beautifulsoup4 not installed"},
            )

        soup = BeautifulSoup(file_bytes, "html.parser")
        metadata: dict[str, Any] = self._extract_meta(soup)

        title = ""
        title_tag = soup.find("title")
        if title_tag and title_tag.text:
            title = title_tag.text.strip()

        headings: list[Heading] = []
        for level in range(1, 7):
            for tag in soup.find_all(f"h{level}"):
                text = tag.get_text(strip=True)
                if text:
                    headings.append(Heading(level=level, text=text))
        if not title and headings:
            title = headings[0].text

        paragraphs: list[Paragraph] = []
        for tag in soup.find_all(["p", "article", "section"]):
            text = tag.get_text(" ", strip=True)
            if text and not tag.find_parent(["script", "style"]):
                paragraphs.append(Paragraph(text=text))

        tables: list[Table] = []
        for table in soup.find_all("table"):
            rows: list[list[str]] = [
                [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
                for row in table.find_all("tr")
                if row.find_all(["td", "th"])
            ]
            if rows:
                headers = rows[0]
                data = rows[1:]
                caption = ""
                caption_tag = table.find("caption")
                if caption_tag:
                    caption = caption_tag.get_text(strip=True)
                tables.append(Table(headers=headers, rows=data, caption=caption or None))

        code_blocks: list[CodeBlock] = []
        for pre in soup.find_all("pre"):
            code_tag = pre.find("code")
            if code_tag:
                language = None
                for cls in code_tag.get("class", []):
                    if cls.startswith("language-"):
                        language = cls[len("language-"):]
                        break
                code = code_tag.get_text("\n", strip=True)
                code_blocks.append(CodeBlock(language=language, code=code))
            else:
                code_blocks.append(CodeBlock(language=None, code=pre.get_text("\n", strip=True)))

        links: list[Link] = []
        seen_links = set()
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            url = a["href"].strip()
            key = (text, url)
            if key not in seen_links:
                seen_links.add(key)
                links.append(Link(text=text, url=url))

        lists: list[ListItem] = []
        for ol in soup.find_all(["ol"]):
            for idx, li in enumerate(ol.find_all("li"), start=1):
                text = li.get_text(" ", strip=True)
                if text:
                    lists.append(ListItem(text=text, ordered=True))
        for ul in soup.find_all(["ul"]):
            for li in ul.find_all("li"):
                text = li.get_text(" ", strip=True)
                if text:
                    lists.append(ListItem(text=text, ordered=False))

        if not title:
            title = filename.rsplit(".", 1)[0] if "." in filename else filename

        return ExtractedDocument(
            id=None,
            title=title,
            headings=headings,
            paragraphs=paragraphs,
            tables=tables,
            lists=lists,
            code_blocks=code_blocks,
            links=links,
            metadata=metadata,
            source=filename,
            hash=doc_hash,
        )

    @staticmethod
    def _extract_meta(soup: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for tag in soup.find_all("meta"):
            name = (tag.get("name") or tag.get("property") or "").lower()
            content = tag.get("content")
            if name and content:
                meta[name] = content
        return meta
