from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket

class AdminWebSocketManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.topics: dict[str, set[str]] = defaultdict(set)
        self._admin_ids: dict[WebSocket, str] = {}

    async def connect(
        self,
        websocket: WebSocket,
        admin_id: str,
        *,
        already_accepted: bool = False,
    ) -> None:
        if not already_accepted:
            await websocket.accept()
        self.active_connections.setdefault(admin_id, []).append(websocket)
        self._admin_ids[websocket] = admin_id
        self.topics[f"admin:{admin_id}"].add(admin_id)

    async def disconnect(self, websocket: WebSocket) -> None:
        admin_id = self._admin_ids.pop(websocket, None)
        if admin_id and admin_id in self.active_connections:
            self.active_connections[admin_id].remove(websocket)
            if not self.active_connections[admin_id]:
                del self.active_connections[admin_id]
                for subscribers in self.topics.values():
                    subscribers.discard(admin_id)

    async def send_to_admin(self, admin_id: str, message: dict[str, Any]) -> None:
        connections = self.active_connections.get(admin_id, [])
        for connection in connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                await self.disconnect(connection)

    async def broadcast(self, message: dict[str, Any], exclude_admin_id: str | None = None) -> None:
        for admin_id, connections in self.active_connections.items():
            if exclude_admin_id and admin_id == exclude_admin_id:
                continue
            for connection in connections[:]:
                try:
                    await connection.send_json(message)
                except Exception:
                    await self.disconnect(connection)

    async def broadcast_to_topic(self, topic: str, message: dict[str, Any], exclude_admin_id: str | None = None) -> None:
        admin_ids = self.topics.get(topic, set())
        for admin_id in admin_ids:
            if exclude_admin_id and admin_id == exclude_admin_id:
                continue
            await self.send_to_admin(admin_id, message)

    async def subscribe_to_topic(self, admin_id: str, topic: str) -> None:
        self.topics[topic].add(admin_id)

    async def unsubscribe_from_topic(self, admin_id: str, topic: str) -> None:
        self.topics[topic].discard(admin_id)

    async def send_pong(self, websocket: WebSocket) -> None:
        try:
            await websocket.send_json({"type": "pong"})
        except Exception:
            pass

    def connection_count(self) -> int:
        return sum(len(conns) for conns in self.active_connections.values())


admin_ws_manager = AdminWebSocketManager()
