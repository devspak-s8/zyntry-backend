from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import select
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
                user_id=user_id,
                organization_id=organization_id,
            )
            self.db.add(record)
            await self.db.flush()
        return record

    async def get_user_fingerprints(self, user_id: str, limit: int = 50, offset: int = 0) -> list[UserFingerprint]:
        return await self._repo.list_by_user(user_id, limit=limit, offset=offset)

    async def get_fingerprint_history(self, fingerprint_hash: str, limit: int = 50) -> list[UserFingerprint]:
        return await self._repo.list_by_user(user_id="")

    async def get_previous_countries(self, user_id: str, since: datetime | None = None) -> list[str]:
        return []

    async def get_previous_ips(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []

    async def get_previous_sessions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []

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