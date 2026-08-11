from __future__ import annotations

import asyncio
import ipaddress
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.connectors import registry
from app.services.connectors.base import BaseConnector


class WebsiteConnector(BaseConnector):
    """Bounded, same-origin crawler for public HTTP(S) knowledge sources."""

    USER_AGENT = "ZyntryKnowledgeCrawler/1.0"
    MAX_PAGES_LIMIT = 25
    MAX_RESPONSE_BYTES = 2_000_000

    def _url(self) -> str | None:
        value = self.config.get("url") or self.credentials.get("url")
        return value.strip() if isinstance(value, str) and value.strip() else None

    async def _validate_public_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Website URL must use http or https")

        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValueError("Website hostname could not be resolved") from exc

        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Private or local website addresses are not allowed")

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        current = url
        for _ in range(6):
            await self._validate_public_url(current)
            response = await client.get(current, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            if len(response.content) > self.MAX_RESPONSE_BYTES:
                raise ValueError("Website response is too large")
            return response
        raise ValueError("Website redirected too many times")

    @staticmethod
    def _extract_page(url: str, response: httpx.Response) -> tuple[str, str, list[str]]:
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            raise ValueError("Website did not return HTML or plain text")
        if "text/plain" in content_type:
            return url, response.text.strip(), []

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "template"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else url
        text = "\n".join(
            line for line in (part.strip() for part in soup.get_text("\n").splitlines()) if line
        )
        links = [urljoin(url, anchor.get("href")) for anchor in soup.find_all("a", href=True)]
        return title, text, links

    async def _crawl(self, *, include_content: bool) -> list[dict[str, Any]]:
        start_url = self._url()
        if not start_url:
            raise ValueError("Missing website URL")
        start_url = urldefrag(start_url)[0]
        start_origin = urlparse(start_url).netloc.lower()
        requested_max = self.config.get("max_pages", 10)
        try:
            max_pages = max(1, min(int(requested_max), self.MAX_PAGES_LIMIT))
        except (TypeError, ValueError):
            max_pages = 10

        queue = [start_url]
        queued = {start_url}
        visited: set[str] = set()
        items: list[dict[str, Any]] = []
        headers = {"User-Agent": self.USER_AGENT, "Accept": "text/html,text/plain;q=0.9"}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            while queue and len(items) < max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                response = await self._fetch(client, url)
                final_url = urldefrag(str(response.url))[0]
                if urlparse(final_url).netloc.lower() != start_origin:
                    continue
                title, text, links = self._extract_page(final_url, response)
                if text:
                    item: dict[str, Any] = {
                        "url": final_url,
                        "title": title,
                        "content_length": len(text),
                        "content_type": response.headers.get("content-type", ""),
                    }
                    if include_content:
                        item["content"] = text
                    items.append(item)
                for link in links:
                    normalized = urldefrag(link)[0]
                    parsed = urlparse(normalized)
                    if (
                        parsed.scheme in {"http", "https"}
                        and parsed.netloc.lower() == start_origin
                        and normalized not in queued
                    ):
                        queued.add(normalized)
                        queue.append(normalized)
        return items

    async def connect(self) -> dict:
        result = await self.test()
        self._status = {
            "status": "connected" if result.get("success") else "error",
            "message": result.get("message", ""),
        }
        return self._status

    async def test(self) -> dict:
        url = self._url()
        if not url:
            return {"success": False, "message": "Missing website URL"}
        try:
            await self._validate_public_url(url)
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": self.USER_AGENT},
            ) as client:
                response = await self._fetch(client, url)
            return {
                "success": True,
                "message": f"Website reachable: {response.url}",
                "status_code": response.status_code,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {"success": False, "message": str(exc)}

    async def discover(self) -> dict:
        try:
            items = await self._crawl(include_content=False)
            return {"items": items, "total": len(items)}
        except (httpx.HTTPError, ValueError) as exc:
            return {"items": [], "total": 0, "error": str(exc)}

    async def sync(self, options: dict | None = None) -> dict:
        started_at = datetime.now(UTC).isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        try:
            items = await self._crawl(include_content=True)
        except (httpx.HTTPError, ValueError) as exc:
            self._status = {"status": "failed", "progress": 0, "error": str(exc)}
            return {
                "job_id": str(uuid.uuid4()),
                "status": "failed",
                "started_at": started_at,
                "error": str(exc),
                "items": [],
                "total": 0,
            }
        self._status = {"status": "completed", "progress": 100, "items_synced": len(items)}
        return {
            "job_id": str(uuid.uuid4()),
            "status": "completed",
            "progress": 100,
            "started_at": started_at,
            "items": items,
            "total": len(items),
        }

    async def get_status(self) -> dict:
        return self._status

    async def disconnect(self) -> dict:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict:
        return await self.test()

    def validate(self) -> dict:
        url = self._url()
        errors = [] if url else ["Missing website URL"]
        return {"valid": not errors, "errors": errors}

    def watch(self, poll_interval: int = 120) -> Any:
        return None


registry.register("website", WebsiteConnector)
registry.register("crawler", WebsiteConnector)
