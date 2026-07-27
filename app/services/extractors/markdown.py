from __future__ import annotations

import re

from app.extractors.base import BaseExtractor, CodeBlock, ExtractedDocument, Heading, Link, ListItem, Paragraph


class MarkdownExtractor(BaseExtractor):
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    LIST_RE = re.compile(r"^(?:[-\*]\s+|(\d+)\.\s+)(.+)$", re.MULTILINE)
    CODE_RE = re.compile(r"^```(\w+)?\n(.*?)^```$", re.MULTILINE | re.DOTALL)
    LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
    ITALIC_RE = re.compile(r"\*(.+?)\*|_(.+?)_")

    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        doc_hash = self._hash_bytes(file_bytes)
        raw = file_bytes.decode("utf-8", errors="replace")
        metadata: dict[str, Any] = {"raw_length": len(raw)}

        headings: list[Heading] = []
        paragraphs: list[Paragraph] = []
        code_blocks: list[CodeBlock] = []
        lists: list[ListItem] = []
        links: list[Link] = []

        for match in self.HEADING_RE.finditer(raw):
            headings.append(Heading(level=len(match.group(1)), text=match.group(2).strip()))

        code_match = self.CODE_RE.search(raw)
        if code_match:
            code_blocks.append(
                CodeBlock(
                    language=code_match.group(1) if code_match.group(1) else None,
                    code=code_match.group(2).strip(),
                )
            )

        stripped_headings = "\n".join(m.group(0) for m in self.HEADING_RE.finditer(raw))
        split_sections = re.split(r"#{1,6}\s+.+", raw)
        for section in split_sections:
            lines = section.splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("```", "#", "-", "*")) or stripped[0].isdigit() and stripped[1:3] == ". ":
                    continue
                paragraphs.append(Paragraph(text=stripped))

        for match in self.LIST_RE.finditer(raw):
            ordered = match.group(1) is not None
            lists.append(ListItem(text=match.group(2).strip(), ordered=ordered))

        links_set = set()
        for match in self.LINK_RE.finditer(raw):
            text = match.group(1)
            url = match.group(2)
            key = (text, url)
            if key not in links_set:
                links_set.add(key)
                links.append(Link(text=text, url=url))

        title = headings[0].text if headings else filename.rsplit(".", 1)[0] if "." in filename else filename

        return ExtractedDocument(
            id=None,
            title=title,
            headings=headings,
            paragraphs=paragraphs,
            lists=lists,
            code_blocks=code_blocks,
            links=links,
            metadata=metadata,
            source=filename,
            hash=doc_hash,
        )
