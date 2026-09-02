from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.admin.auth import decode_token, extract_token_from_request, get_client_ip
from app.admin.metrics import record_admin_request


class AdminSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            return await call_next(request)

        start_time = time.time()
        client_ip = get_client_ip(request)

        response = await call_next(request)

        duration = time.time() - start_time
        token = extract_token_from_request(request)

        if token:
            try:
                payload = decode_token(token)
                admin_id = payload.get("admin_id")
                if admin_id:
                    record_admin_request(request.method, request.url.path, response.status_code, duration)
                    await self._publish_ws_event(request, response, duration, client_ip, admin_id)
            except Exception:
                pass

        return response

    async def _record_audit_log(self, request: Request, response: Response, duration: float, ip: str, admin_id: str | None) -> None:
        pass

    async def _publish_ws_event(self, request: Request, response: Response, duration: float, ip: str, admin_id: str) -> None:
        try:
            from app.admin.websocket_manager import admin_ws_manager
            await admin_ws_manager.send_to_admin(
                str(admin_id),
                {
                    "type": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "ip": ip,
                },
            )
        except Exception:
            pass
