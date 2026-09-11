"""Typed application errors and safe public error rendering.

Service code can raise a :class:`DomainError` when a caller should receive a
known, safe message. Unexpected exceptions are logged with their traceback,
but are never serialized into an API response.
"""

from __future__ import annotations

from dataclasses import dataclass


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
