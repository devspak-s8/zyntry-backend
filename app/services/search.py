from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SearchResult(BaseModel):
    id: str
    document_id: str | None = None
    score: float = 0.0
    text: str = ""
    metadata: dict[str, Any] = {}
    source: str | None = None
    page: int | None = None
    heading: str | None = None
    title: str = ""


class SearchRequest(BaseModel):
    query: str
    query_vector: list[float] | None = None
    limit: int = 10
    filters: dict | None = None
    hybrid: bool = True
    rerank: bool = False
    mmr: bool = False
    mmr_lambda: float = 0.5


class QueryExpander:
    @staticmethod
    def expand(query: str) -> str:
        synonyms = {
            "bug": ["error", "issue", "fault"],
            "feature": ["capability", "functionality"],
            "how to": ["guide", "tutorial", "steps"],
            "error": ["exception", "bug", "issue"],
        }
        expanded = [query]
        for term, syns in synonyms.items():
            if term in query.lower():
                expanded.extend(syns)
        return " ".join(expanded)


class RetrievalContext:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def format_for_prompt(self) -> str:
        parts = []
        for r in self.results:
            page = r.page or "?"
            doc = r.document_id or r.source or "unknown"
            text = r.text.strip()
            parts.append(f"[{doc}:{page}] {text}")
        return "\n\n".join(parts)

    def citations(self) -> list[dict[str, Any]]:
        citations = []
        for r in self.results:
            citations.append({
                "document_id": r.document_id,
                "source": r.source,
                "page": r.page,
                "heading": r.heading,
                "title": r.title,
                "text": r.text[:200],
                "score": r.score,
            })
        return citations

    def sources(self) -> list[dict[str, Any]]:
        seen = {}
        for r in self.results:
            key = r.document_id or r.source or r.id
            if key not in seen:
                seen[key] = {
                    "id": r.document_id or r.id,
                    "title": r.title or r.source or "Unknown",
                    "source": r.source,
                    "page": r.page,
                    "relevance_score": r.score,
                }
        return list(seen.values())
