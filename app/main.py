from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.api.v1.logs.router import router as logs_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.middleware import RateLimitMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware


def _parse_cors_origins(value: str) -> list[str]:
    if not value:
        return ["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"]
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
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
            raise RuntimeError(f"Missing required environment variables for production: {', '.join(missing)}")
    yield


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.remove(connection)


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
        allow_origins=_parse_cors_origins(settings.CORS_ORIGINS),
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

    return app


app = create_app()
