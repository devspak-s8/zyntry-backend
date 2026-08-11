from __future__ import annotations

import logging
import secrets
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.middleware.csrf")


class CSRFMiddleware(BaseHTTPMiddleware):
    TOKEN_NAME = "zyntra_csrf"
    HEADER_NAME = "x-csrf-token"

    async def dispatch(self, request: Request, call_next: Callable):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        path = request.url.path

        if path.startswith("/api/v1/auth"):
            return await call_next(request)

        if settings.APP_DEBUG:
            return await call_next(request)

        if not request.cookies.get("zyntra_session"):
            return await call_next(request)

        token = request.cookies.get(self.TOKEN_NAME)
        header_token = request.headers.get(self.HEADER_NAME)

        if not token or not header_token or not secrets.compare_digest(token, header_token):
            logger.warning("CSRF validation failed", extra={"path": path})
            return Response(content='{"detail":"CSRF token missing or invalid"}', status_code=403, media_type="application/json")

        # Keep the double-submit token stable. Rotating it here would leave the
        # browser holding a new HttpOnly cookie while the frontend still has the
        # old response-body token, causing the next mutation to fail.
        return await call_next(request)
