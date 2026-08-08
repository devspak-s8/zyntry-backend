from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import IPRecord
from app.admin.repositories import IPRecordRepository
from app.core.cache import cache as redis_cache


class IPIntelligenceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = IPRecordRepository(db)

    async def get_or_create_ip_record(self, ip_address: str) -> IPRecord:
        result = await self.db.execute(select(IPRecord).where(IPRecord.ip_address == ip_address))
        record = result.scalar_one_or_none()
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
        return record

    async def record_request(self, ip_address: str, success: bool = True, account_created: bool = False, api_key_generated: bool = False, threat_detected: bool = False) -> IPRecord:
        record = await self._repo.get_by_ip(ip_address)
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()

        weight = 1
        if threat_detected:
            weight = 5
        elif not success:
            weight = 3

        record.total_requests += 1
        if not success:
            record.failed_requests += 1
        if account_created:
            record.accounts_created += 1
        if api_key_generated:
            record.api_keys_generated += 1
        if threat_detected:
            record.risk_score = min(100, record.risk_score + weight)
        record.last_seen = datetime.now(UTC)
        await self.db.flush()
        return record

    async def geolocate_ip(self, ip_address: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://ip-api.com/json/{ip_address}", params={"fields": "status,country,countryCode,city,regionName,lat,lon,isp,as"})
                data = resp.json()
                if data.get("status") == "success":
                    return {
                        "country": data.get("country"),
                        "city": data.get("city"),
                        "region": data.get("regionName"),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "isp": data.get("isp"),
                        "asn": data.get("as"),
                    }
        except Exception:
            pass
        return {}

    async def enrich_ip_record(self, ip_address: str, record: IPRecord | None) -> IPRecord:
        if record is None:
            record = await self._repo.get_by_ip(ip_address)
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
            return record

        geo = await self.geolocate_ip(ip_address)
        if geo:
            record.country = geo.get("country")
            record.city = geo.get("city")
            record.region = geo.get("region")
            record.latitude = geo.get("latitude")
            record.longitude = geo.get("longitude")
            record.isp = geo.get("isp")
            record.asn = geo.get("asn")
            await self.db.flush()

        return record

    async def ban_ip(self, ip_address: str, ban_type: str = "temporary", reason: str | None = None, duration_hours: int | None = None) -> IPRecord:
        return await self._repo.ban_ip(ip_address, ban_type, reason, duration_hours)

    async def unban_ip(self, ip_address: str) -> IPRecord | None:
        return await self._repo.unban_ip(ip_address)

    async def whitelist_ip(self, ip_address: str) -> IPRecord:
        record = await self._repo.get_by_ip(ip_address)
        if record:
            record.is_banned = False
            record.ban_type = None
            record.ban_reason = None
            record.ban_expires_at = None
            await self.db.flush()
        return record

    async def blacklist_ip(self, ip_address: str, reason: str | None = None) -> IPRecord:
        return await self._repo.ban_ip(ip_address, ban_type="permanent", reason=reason)

    async def rate_limit_ip(self, ip_address: str, limit: int = 100, window_seconds: int = 60) -> bool:
        key = f"admin:ratelimit:{ip_address}"
        current = await redis_cache.get(key)
        if current is None:
            await redis_cache.set(key, 1, expire=window_seconds)
            return True
        if int(current) >= limit:
            return False
        await redis_cache.incr(key)
        return True

    async def get_ip_stats(self, ip_address: str) -> dict[str, Any]:
        record = await self._repo.get_by_ip(ip_address)
        if record is None:
            return {"ip_address": ip_address}
        return {
            "ip_address": record.ip_address,
            "country": record.country,
            "city": record.city,
            "asn": record.asn,
            "isp": record.isp,
            "is_vpn": record.is_vpn,
            "is_proxy": record.is_proxy,
            "is_tor": record.is_tor,
            "total_requests": record.total_requests,
            "failed_requests": record.failed_requests,
            "accounts_created": record.accounts_created,
            "api_keys_generated": record.api_keys_generated,
            "risk_score": record.risk_score,
            "is_banned": record.is_banned,
            "ban_type": record.ban_type,
            "ban_reason": record.ban_reason,
            "first_seen": record.first_seen.isoformat() if record.first_seen else "",
            "last_seen": record.last_seen.isoformat() if record.last_seen else "",
        }

    async def list_ips(self, limit: int = 50, offset: int = 0, min_risk: int = 0, is_banned: bool | None = None, country: str | None = None) -> list[IPRecord]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def get_top_ips_by_risk(self, limit: int = 10) -> list[IPRecord]:
        return await self._repo.list_by_risk(min_score=70, limit=limit)