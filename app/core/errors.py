"""Typed application errors and safe public error rendering.

Service code can raise a :class:`DomainError` when a caller should receive a
known, safe message. Unexpected exceptions are logged with their traceback,
but are never serialized into an API response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_TECHNICAL_ERROR_PATTERNS = (
    re.compile(r"traceback \(most recent call last\)", re.I),
    re.compile(r"stack\s*trace|stacktrace", re.I),
    re.compile(r"\b(?:sqlalchemy|asyncpg|psycopg|redis|uvicorn|fastapi|pydantic)\b", re.I),
    re.compile(r"(?:file\s+\"|line\s+\d+|errno\s*[:=]|connection refused|connection reset)", re.I),
    re.compile(r"\b(?:nullpointer|attributeerror|keyerror|typeerror|valueerror|operationalerror)\b", re.I),
)


@dataclass
class DomainError(Exception):
    """An expected application failure with a stable public error contract."""

    message: str
    code: str = "application_error"
    status_code: int = 400

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def as_detail(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }


class NotConfiguredError(DomainError):
    """Raised when an optional provider or connector is not configured."""

    def __init__(self, message: str = "This integration is not configured.") -> None:
        super().__init__(message=message, code="not_configured", status_code=503)


class CapabilityNotSupportedError(DomainError):
    """Raised when a requested connector capability is outside the registry."""

    def __init__(self, message: str = "This capability is not supported yet.") -> None:
        super().__init__(message=message, code="capability_not_supported", status_code=422)


def safe_public_message(exc: Exception, fallback: str = "The operation could not be completed.") -> str:
    """Return only an intentionally safe message for an API/task response."""
    if isinstance(exc, DomainError):
        return exc.message
    return fallback


def _contains_technical_detail(value: str) -> bool:
    return any(pattern.search(value) for pattern in _TECHNICAL_ERROR_PATTERNS)


def safe_http_detail(status_code: int, detail: object) -> object:
    """Keep HTTP error responses useful without exposing implementation details.

    Expected validation and permission messages remain available to clients. Any
    traceback, driver error, file path, or server-side exception is replaced by
    a stable public message; the full exception is still logged by the handler.
    """
    if status_code >= 500:
        return "A temporary service issue occurred. Please try again shortly."

    if isinstance(detail, dict):
        raw_message = detail.get("message") or detail.get("detail")
        if isinstance(raw_message, str) and not _contains_technical_detail(raw_message):
            safe: dict[str, object] = {
                "code": detail.get("code", "request_error"),
                "message": raw_message,
            }
            # These fields are intentionally user-facing policy information,
            # not implementation diagnostics.
            for key in ("guardrail_violations", "policy", "status_code"):
                if key in detail:
                    safe[key] = detail[key]
            return safe
        return {
            "code": detail.get("code", "request_error"),
            "message": "Please review the request and try again.",
        }

    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                location = item.get("loc")
                message = item.get("msg") or item.get("message")
                if isinstance(message, str) and not _contains_technical_detail(message):
                    field = ".".join(str(part) for part in location if part != "body") if isinstance(location, list) else "field"
                    messages.append(f"{field or 'field'}: {message}")
        return "; ".join(messages) if messages else "Please review the highlighted fields and try again."

    if isinstance(detail, str):
        text = detail.strip()
        if text:
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed != detail:
                return safe_http_detail(status_code, parsed)
            if not _contains_technical_detail(text):
                return text

    return "Please review the request and try again."
