from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.admin.auth import decode_token as decode_admin_token
from app.admin.middleware import AdminSecurityMiddleware
from app.admin.models import AdminSession, AdminUser
from app.admin.websocket_manager import admin_ws_manager
from app.api import router as api_router
from app.api.v1.logs.router import router as logs_router
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.errors import DomainError
from app.core.lifecycle import start_application, stop_application
from app.core.logging import get_logger
from app.core.security import hash_token, now
from app.middleware import RateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.models.sessions import Session
from app.models.users import User

logger = get_logger("app.main")


def _parse_cors_origins(value: str) -> list[str]:
    # Compatibility helper for callers that import this function directly;
    # application code uses the normalized settings property below.
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime_event_task = await start_application(settings, manager.broadcast)
    try:
        yield
    finally:
        await stop_application(runtime_event_task)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.user_ids: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self.active_connections.setdefault(user_id, []).append(websocket)
        self.user_ids[websocket] = user_id

    def disconnect(self, websocket: WebSocket) -> None:
        user_id = self.user_ids.pop(websocket, None)
        if user_id and user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, message: dict, user_id: str) -> None:
        connections = self.active_connections.get(user_id, [])
        for connection in connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                logger.debug("Removing disconnected user websocket", exc_info=True)
                self.disconnect(connection)

    async def broadcast(self, message: dict) -> None:
        # Runtime events carry their owner so a status transition cannot be
        # observed by every connected tenant. Events without an owner remain
        # broadcast-compatible for legacy system notifications.
        owner_user_id = message.get("user_id")
        if owner_user_id:
            await self.send_to_user(message, str(owner_user_id))
            return
        for connections in list(self.active_connections.values()):
            for connection in connections[:]:
                try:
                    await connection.send_json(message)
                except Exception:
                    logger.debug("Removing disconnected broadcast websocket", exc_info=True)
                    self.disconnect(connection)


manager = ConnectionManager()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.API_VERSION,
        debug=settings.APP_DEBUG,
        lifespan=lifespan,
    )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Keep tracebacks and provider/database details out of API responses."""
        logger.exception(
            "Unhandled application error",
            extra={"path": request.url.path, "method": request.method},
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "An internal error occurred. Please try again.",
            },
        )

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_detail())

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware, limit=settings.RATE_LIMIT_PER_MINUTE, window=60)
    app.add_middleware(AdminSecurityMiddleware)
    # Starlette applies middleware in reverse registration order. Keep CORS
    # outermost so browser clients receive CORS headers on handled failures as
    # well as successful API responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=f"{settings.API_PREFIX}/{settings.API_VERSION}")
    app.include_router(logs_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.options("/api/v1/auth/refresh", tags=["auth"])
    async def auth_refresh_preflight() -> Response:
        return Response(status_code=200)

    @app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        await _handle_client_websocket(websocket)

    @app.websocket("/ws/runtimes")
    async def websocket_runtimes(websocket: WebSocket):
        await _handle_client_websocket(websocket)

    @app.websocket("/ws/admin")
    async def websocket_admin(websocket: WebSocket):
        origin = websocket.headers.get("origin", "")
        allowed_origins = set(settings.cors_origins)
        if origin and origin not in allowed_origins:
            await websocket.close(code=4003, reason="Origin not allowed")
            return

        auth_header = websocket.headers.get("authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        already_accepted = False
        if not token:
            # Browsers cannot set Authorization headers on WebSocket
            # handshakes. Authenticate with the first TLS-protected message
            # instead of putting credentials in the URL/query string.
            await websocket.accept()
            already_accepted = True
            try:
                auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                if auth_message.get("type") != "authenticate":
                    raise ValueError("authentication message required")
                token = str(auth_message.get("token") or "")
                if not token:
                    raise ValueError("token required")
            except (TimeoutError, ValueError, TypeError, WebSocketDisconnect):
                await websocket.close(code=4001, reason="Not authenticated")
                return
        try:
            payload = decode_admin_token(token)
            if payload.get("type") != "admin_access":
                raise ValueError("invalid token type")
            admin_id = uuid.UUID(str(payload["admin_id"]))
            user_id = uuid.UUID(str(payload["user_id"]))
        except (KeyError, TypeError, ValueError, HTTPException):
            await websocket.close(code=4001, reason="Invalid token")
            return

        async with async_session_factory() as db:
            session_result = await db.execute(
                select(AdminSession).where(AdminSession.token_hash == hash_token(token))
            )
            admin_session = session_result.scalar_one_or_none()
            admin_result = await db.execute(select(AdminUser).where(AdminUser.id == admin_id))
            admin_user = admin_result.scalar_one_or_none()
            admin_expires_at = getattr(admin_session, "expires_at", None)
            if admin_expires_at is not None and admin_expires_at.tzinfo is None:
                from datetime import UTC
                admin_expires_at = admin_expires_at.replace(tzinfo=UTC)
            if (
                admin_session is None
                or admin_session.revoked
                or admin_expires_at is None
                or admin_expires_at <= now()
                or admin_session.admin_user_id != admin_id
                or admin_session.user_id != user_id
                or admin_user is None
                or not admin_user.is_active
            ):
                await websocket.close(code=4001, reason="Invalid session")
                return

        await admin_ws_manager.connect(
            websocket,
            admin_id=str(admin_id),
            already_accepted=already_accepted,
        )
        await websocket.send_json({"type": "connected", "transport": "websocket"})
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await admin_ws_manager.send_pong(websocket)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug("Ignoring malformed admin websocket message")
        except WebSocketDisconnect:
            await admin_ws_manager.disconnect(websocket)

    async def _handle_client_websocket(websocket: WebSocket):
        origin = websocket.headers.get("origin", "")
        allowed_origins = set(settings.cors_origins)
        if origin and origin not in allowed_origins:
            await websocket.close(code=4003, reason="Origin not allowed")
            return

        # Tokens in query strings leak through browser history, reverse-proxy
        # logs and referrers. Browser clients already send the session cookie;
        # non-browser clients may use the Authorization header.
        auth_header = websocket.headers.get("authorization", "")
        bearer_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
        session_token = websocket.cookies.get("zyntra_session") or bearer_token
        if not session_token:
            await websocket.close(code=4001, reason="Not authenticated")
            return

        token_hash = hash_token(session_token)
        async with async_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.token_hash == token_hash)
            )
            session_obj = result.scalar_one_or_none()

            expires_at = getattr(session_obj, "expires_at", None)
            if expires_at is not None and expires_at.tzinfo is None:
                from datetime import UTC
                expires_at = expires_at.replace(tzinfo=UTC)
            if session_obj is None or session_obj.revoked or expires_at is None or expires_at <= now():
                await websocket.close(code=4001, reason="Invalid session")
                return

            user = await db.get(User, session_obj.user_id)
            if user is None or not user.is_active:
                await websocket.close(code=4001, reason="User not found")
                return

            user_id = str(user.id)

        await manager.connect(websocket, user_id)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug("Ignoring malformed realtime websocket message")
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.websocket("/ws/realtime")
    async def websocket_realtime(websocket: WebSocket):
        await _handle_client_websocket(websocket)

    @app.websocket("/api/v1/ws")
    async def websocket_api(websocket: WebSocket):
        await _handle_client_websocket(websocket)

    @app.websocket("/ws")
    async def websocket_default(websocket: WebSocket):
        await _handle_client_websocket(websocket)

    return app


app = create_app()
