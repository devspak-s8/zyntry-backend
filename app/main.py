from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import router as api_router
from app.api.v1.logs.router import router as logs_router
from app.core.config import settings
from app.core.database import async_session_factory, init_models
from app.core.logging import configure_logging
from app.core.security import hash_token, now
from app.middleware import RateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.models.sessions import Session
from app.models.users import User


def _parse_cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_models()
    if not settings.APP_DEBUG:
        missing = []
        if not settings.SECRET_KEY:
            missing.append("SECRET_KEY")
        if not settings.JWT_SECRET:
            missing.append("JWT_SECRET")
        if not settings.ENCRYPTION_KEY:
            missing.append("ENCRYPTION_KEY")
        if not settings.DATABASE_URL or settings.DATABASE_URL in ("postgresql+asyncpg://zyntra:zyntra@localhost:5432/zyntra",):
            missing.append("DATABASE_URL")
        if missing:
            msg = (
                "Missing required environment variables "
                f"for production: {', '.join(missing)}"
            )
            raise RuntimeError(msg)
    yield


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
                self.disconnect(connection)

    async def broadcast(self, message: dict) -> None:
        for connections in list(self.active_connections.values()):
            for connection in connections[:]:
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection)


manager = ConnectionManager()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.API_VERSION,
        debug=settings.APP_DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|zyntry\.space|.*\.zyntry\.space|.*\.railway\.app|.*\.railway\.internal)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware, limit=settings.RATE_LIMIT_PER_MINUTE, window=60)

    app.include_router(api_router, prefix=f"{settings.API_PREFIX}/{settings.API_VERSION}")
    app.include_router(logs_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.options("/api/v1/auth/refresh", tags=["auth"])
    async def auth_refresh_preflight() -> Response:
        return Response(status_code=200)

    @app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.websocket("/ws/runtimes")
    async def websocket_runtimes(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.websocket("/api/v1/ws")
    async def websocket_api(websocket: WebSocket):
        origin = websocket.headers.get("origin", "")
        allowed_regex = re.compile(r"https?://(localhost|zyntry\.space|.*\.zyntry\.space|.*\.railway\.app|.*\.railway\.internal)(:\d+)?")
        if origin and not allowed_regex.match(origin):
            await websocket.close(code=4003, reason="Origin not allowed")
            return

        session_token = websocket.cookies.get("zyntra_session")
        if not session_token:
            await websocket.close(code=4001, reason="Not authenticated")
            return

        token_hash = hash_token(session_token)
        async with async_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.token_hash == token_hash)
            )
            session_obj = result.scalar_one_or_none()

            if session_obj is None or session_obj.revoked or session_obj.expires_at <= now():
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
                except (json.JSONDecodeError, Exception):
                    pass
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


app = create_app()
