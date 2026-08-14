from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


_SECRET_KEY_PARTS = (
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "token",
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[a-z0-9._~+\-/]+=*")
_ZYNTRY_KEY = re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9_-]+\b")


def redact_sensitive(value: Any) -> Any:
    """Recursively redact credentials before assistant output or persistence."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return redact_sensitive(value.value)
    if isinstance(value, str):
        value = _BEARER.sub(r"\1[REDACTED]", value)
        return _ZYNTRY_KEY.sub("[REDACTED]", value)
    return value
