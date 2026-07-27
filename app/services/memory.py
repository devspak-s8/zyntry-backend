from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.memory import MemoryRecord
from app.repositories import UnitOfWork
from app.schemas.memory import MemoryRecordCreate, MemoryToggleRequest

DEFAULT_TTL_BY_TYPE: dict[str, timedelta | None] = {
    "session": timedelta(hours=24),
    "conversation": timedelta(days=7),
    "long_term": timedelta(days=365),
    "project": None,
}


class MemoryService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list_records(self, project_id: str) -> list[dict]:
        return await self.list_memories(project_id=project_id)

    async def create_record(self, data: MemoryRecordCreate) -> dict:
        return await self.add_memory(
            key=data.key,
            value=data.value,
            content=data.content or "",
            memory_type=data.memory_type,
            project_id=data.project_id,
            user_id=data.user_id,
            conversation_id=data.conversation_id,
            session_id=data.session_id,
            ttl=data.ttl,
            pinned=data.pinned,
        )

    async def toggle_project_memory(self, data: MemoryToggleRequest) -> dict:
        project = await self.uow.projects.get(data.project_id)
        if not project:
            raise ValueError("Project not found")
        updated = await self.uow.projects.update(
            project, memory_enabled=data.enabled
        )
        await self.uow.commit()
        return {
            "project_id": str(updated.id),
            "memory_enabled": updated.memory_enabled,
        }

    async def add_memory(
        self,
        key: str,
        value: dict[str, Any],
        content: str,
        memory_type: str = "long_term",
        project_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        session_id: str | None = None,
        ttl: int | None = None,
        pinned: bool = False,
    ) -> dict:
        pid = uuid.UUID(project_id) if project_id else None
        uid = uuid.UUID(user_id) if user_id else None
        cid = uuid.UUID(conversation_id) if conversation_id else None

        now = datetime.now(UTC)
        if pinned:
            expires_at = None
        elif ttl is not None:
            expires_at = now + timedelta(seconds=ttl)
        else:
            delta = DEFAULT_TTL_BY_TYPE.get(memory_type)
            expires_at = (now + delta) if delta else None

        existing = None
        if pid:
            existing = await self.uow.memory_records.get_by_key_and_scope(
                project_id=pid,
                key=key,
                user_id=uid,
                conversation_id=cid,
                session_id=session_id,
            )

        if existing:
            record = await self.uow.memory_records.update(
                existing,
                value=value or existing.value,
                content=content or existing.content,
                memory_type=memory_type,
                user_id=uid or existing.user_id,
                conversation_id=cid if cid else existing.conversation_id,
                session_id=session_id or existing.session_id,
                pinned=pinned,
                expires_at=expires_at if expires_at else existing.expires_at,
            )
        else:
            if pid is None:
                raise ValueError("project_id is required to add memory")
            record = await self.uow.memory_records.create(
                key=key,
                value=value or {},
                content=content,
                memory_type=memory_type,
                project_id=pid,
                user_id=uid,
                conversation_id=cid,
                session_id=session_id,
                pinned=pinned,
                expires_at=expires_at,
            )

        await self.uow.commit()
        return self._to_dict(record)

    async def get_memory(
        self,
        key: str,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> dict | None:
        if not project_id:
            return None
        pid = uuid.UUID(project_id)
        uid = uuid.UUID(user_id) if user_id else None
        record = await self.uow.memory_records.get_by_key_and_scope(
            project_id=pid,
            key=key,
            user_id=uid,
        )
        if not record:
            return None
        if (
            record.expires_at
            and record.expires_at < datetime.now(UTC)
            and not record.pinned
        ):
            return None
        return self._to_dict(record)

    async def search_memories(
        self,
        query: str,
        project_id: str | None = None,
        user_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        if not project_id:
            return []
        pid = uuid.UUID(project_id)
        uid = uuid.UUID(user_id) if user_id else None
        records = await self.uow.memory_records.search(
            project_id=pid,
            query=query,
            user_id=uid,
            memory_type=memory_type,
            limit=limit,
        )
        now = datetime.now(UTC)
        scored = []
        q = query.lower()
        for r in records:
            if r.expires_at and r.expires_at < now and not r.pinned:
                continue
            score = self._compute_text_score(q, r.content or "", r.key)
            entry = self._to_dict(r)
            entry["score"] = score
            scored.append(entry)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    async def summarize_conversation(self, conversation_id: str) -> dict | None:
        cid = uuid.UUID(conversation_id)
        records = await self.uow.memory_records.get_by_conversation_id(cid)
        if not records:
            return None

        messages = sorted(
            [r for r in records if r.content and not r.parent_key],
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC),
        )
        if not messages:
            return None

        chunks = [m.content for m in messages if m.content]
        summary_content = self._build_summary(chunks)

        summary_key = f"conversation_summary:{conversation_id}"
        existing = await self.uow.memory_records.get_by_parent_key(summary_key)
        project_id = messages[0].project_id
        user_id = messages[0].user_id
        session_id = messages[0].session_id

        pid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id
        uid = uuid.UUID(user_id) if user_id else None

        if existing:
            record = await self.uow.memory_records.update(
                existing,
                value={
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "message_count": len(messages),
                    "summary": summary_content,
                },
                content=summary_content,
            )
        else:
            record = await self.uow.memory_records.create(
                key=summary_key,
                value={
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "message_count": len(messages),
                    "summary": summary_content,
                },
                content=summary_content,
                memory_type="conversation",
                project_id=pid,
                user_id=uid,
                conversation_id=cid,
                session_id=session_id,
                parent_key=summary_key,
            )

        await self.uow.commit()
        return self._to_dict(record)

    async def list_memories(
        self,
        project_id: str | None = None,
        user_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if not project_id:
            return []
        pid = uuid.UUID(project_id)
        uid = uuid.UUID(user_id) if user_id else None
        records = await self.uow.memory_records.list_by_scope(
            project_id=pid,
            user_id=uid,
            memory_type=memory_type,
            limit=limit,
        )
        now = datetime.now(UTC)
        return [
            self._to_dict(r)
            for r in records
            if not (r.expires_at and r.expires_at < now and not r.pinned)
        ]

    async def delete_memory(
        self,
        key: str,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        if not project_id:
            return False
        pid = uuid.UUID(project_id)
        uid = uuid.UUID(user_id) if user_id else None
        record = await self.uow.memory_records.get_by_key_and_scope(
            project_id=pid,
            key=key,
            user_id=uid,
        )
        if not record:
            return False
        await self.uow.memory_records.delete(record)
        await self.uow.commit()
        return True

    async def cleanup_expired(self) -> int:
        now = datetime.now(UTC)
        expired = await self.uow.memory_records.get_expired(now)
        count = 0
        for record in expired:
            if record.pinned:
                continue
            await self.uow.memory_records.delete(record)
            count += 1
        if count > 0:
            await self.uow.commit()
        return count

    def _to_dict(self, record: MemoryRecord) -> dict:
        return {
            "id": str(record.id),
            "key": record.key,
            "value": record.value or {},
            "content": record.content,
            "memory_type": record.memory_type,
            "project_id": str(record.project_id) if record.project_id else None,
            "user_id": str(record.user_id) if record.user_id else None,
            "conversation_id": str(record.conversation_id) if record.conversation_id else None,
            "session_id": record.session_id,
            "pinned": record.pinned,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "parent_key": record.parent_key,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def _compute_text_score(query_lower: str, content: str, key: str) -> float:
        score = 0.0
        if query_lower in (key or "").lower():
            score += 0.3
        if query_lower in (content or "").lower():
            score += 1.0
        return score

    @staticmethod
    def _build_summary(chunks: list[str]) -> str:
        if len(chunks) <= 3:
            return "\n\n".join(chunks)
        first = chunks[:2]
        last = chunks[-2:]
        middle_count = len(chunks) - 4
        parts = first + [f"... {middle_count} omitted messages ..."] + last
        return "\n\n".join(parts)
