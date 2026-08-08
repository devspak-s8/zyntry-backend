from __future__ import annotations

import time
import uuid as uuid_lib

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID", str(uuid_lib.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if not settings.APP_DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if settings.CSP_ENABLED and request.url.path not in ("/docs", "/redoc"):
            if settings.APP_DEBUG:
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self' http://localhost:3000 http://localhost:3001 http://localhost:5173; "
                    "connect-src 'self' http://localhost:3000 http://localhost:3001 http://localhost:5173 ws: wss:; "
                    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
                )
            else:
                frontend_origin = settings.FRONTEND_URL or settings.APP_URL
                api_origin = f"{settings.APP_URL.rstrip('/')}/{settings.API_PREFIX}/{settings.API_VERSION}"
                response.headers["Content-Security-Policy"] = (
                    f"default-src 'self' {frontend_origin}; "
                    f"connect-src 'self' {frontend_origin} {api_origin} ws: wss:; "
                    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
                )

        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{duration:.4f}"

        request_id = getattr(request.state, "request_id", None)
        if request_id:
            logger.info(
                "request completed",
                extra={"request_id": request_id, "path": request.url.path, "duration": duration},
            )

        return response
