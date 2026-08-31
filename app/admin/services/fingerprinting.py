from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import UserFingerprint
from app.admin.repositories import LoginEventRepository, UserFingerprintRepository


class FingerprintingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = UserFingerprintRepository(db)
        self._login_repo = LoginEventRepository(db)

    async def create_fingerprint(
        self,
        browser: str | None,
        os_name: str | None,
        device: str | None,
        timezone_str: str | None,
        language: str | None,
        screen_resolution: str | None,
        canvas_fingerprint: str | None,
        webgl_fingerprint: str | None,
        tls_signature: str | None,
        user_agent: str | None,
        behavioral_signals: dict[str, Any] | None,
    ) -> UserFingerprint:
        components = {
            "browser": browser,
            "os": os_name,
            "device": device,
            "timezone": timezone_str,
            "language": language,
            "screen_resolution": screen_resolution,
            "canvas": canvas_fingerprint,
            "webgl": webgl_fingerprint,
            "tls": tls_signature,
            "user_agent": user_agent,
        }
        raw = str(components)
        fingerprint_hash = hashlib.sha256(raw.encode()).hexdigest()

        fp = UserFingerprint(
            fingerprint_hash=fingerprint_hash,
            browser=browser,
            os_name=os_name,
            device=device,
            timezone=timezone_str,
            language=language,
            screen_resolution=screen_resolution,
            canvas_fingerprint=canvas_fingerprint,
            webgl_fingerprint=webgl_fingerprint,
            tls_signature=tls_signature,
            metadata_=behavioral_signals,
        )
        self.db.add(fp)
        await self.db.flush()
        return fp

    async def get_or_create_fingerprint(self, fingerprint_hash: str, user_id: str | None = None, organization_id: str | None = None, **kwargs: Any) -> UserFingerprint:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.fingerprint_hash == fingerprint_hash))
        record = result.scalar_one_or_none()
        if record is None:
            record = UserFingerprint(
                fingerprint_hash=fingerprint_hash,
                user_id=uuid.UUID(user_id) if user_id else None,
                organization_id=uuid.UUID(organization_id) if organization_id else None,
            )
            self.db.add(record)
            await self.db.flush()
        return record

    async def get_user_fingerprints(self, user_id: str, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        return await self._repo.list_by_user(user_id, limit=limit, offset=offset)

    async def get_fingerprint_history(self, fingerprint_hash: str, limit: int = 50) -> list[UserFingerprint]:
        result = await self.db.execute(
            select(UserFingerprint)
            .where(UserFingerprint.fingerprint_hash == fingerprint_hash)
            .order_by(UserFingerprint.last_seen.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_previous_countries(self, user_id: str, since: datetime | None = None) -> list[str]:
        try:
            parsed_user_id = uuid.UUID(user_id)
        except ValueError:
            return []
        stmt = select(LoginEvent.country).where(LoginEvent.user_id == parsed_user_id, LoginEvent.country.is_not(None))
        if since:
            stmt = stmt.where(LoginEvent.created_at >= since)
        result = await self.db.execute(stmt.distinct())
        return [str(country) for (country,) in result.all() if country]

    async def get_previous_ips(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            parsed_user_id = uuid.UUID(user_id)
        except ValueError:
            return []
        result = await self.db.execute(
            select(LoginEvent.ip_address, func.count(LoginEvent.id).label("events"), func.max(LoginEvent.created_at).label("last_seen"))
            .where(LoginEvent.user_id == parsed_user_id)
            .group_by(LoginEvent.ip_address)
            .order_by(func.max(LoginEvent.created_at).desc())
            .limit(limit)
        )
        return [
            {"ip_address": ip, "events": int(events or 0), "last_seen": last_seen.isoformat() if last_seen else None}
            for ip, events, last_seen in result.all()
        ]

    async def get_previous_sessions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            parsed_user_id = uuid.UUID(user_id)
        except ValueError:
            return []
        result = await self.db.execute(
            select(LoginEvent)
            .where(LoginEvent.user_id == parsed_user_id)
            .order_by(LoginEvent.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(event.id),
                "session_id": str(event.session_id) if event.session_id else None,
                "ip_address": event.ip_address,
                "country": event.country,
                "success": event.success,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in result.scalars().all()
        ]

    async def detect_impossible_travel(self, user_id: str, new_ip_country: str, new_ip: str) -> dict[str, Any]:
        return {"detected": False, "user_id": user_id, "new_ip_country": new_ip_country}

    async def get_known_devices(self, user_id: str, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        return await self._repo.list_by_user(user_id, limit=limit, offset=offset)

    async def flag_fingerprint(self, fingerprint_hash: str, risk_score: int) -> UserFingerprint | None:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.fingerprint_hash == fingerprint_hash))
        record = result.scalar_one_or_none()
        if record:
            record.risk_score = risk_score
            await self.db.flush()
        return record

    async def list_flagged(self, min_risk: int = 50, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        return await self._repo.list_flagged(min_risk=min_risk, limit=limit, offset=offset)

    async def update_fingerprint_trust(self, fingerprint_hash: str, is_trusted: bool) -> UserFingerprint | None:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.fingerprint_hash == fingerprint_hash))
        record = result.scalar_one_or_none()
        if record:
            record.is_trusted = is_trusted
            await self.db.flush()
        return record

    async def get_fingerprint(self, fingerprint_hash: str) -> UserFingerprint | None:
        result = await self.db.execute(select(UserFingerprint).where(UserFingerprint.fingerprint_hash == fingerprint_hash))
        return result.scalar_one_or_none()
