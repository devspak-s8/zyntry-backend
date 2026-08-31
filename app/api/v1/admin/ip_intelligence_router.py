from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    IPActionRequest,
    IPBanRequest,
    IPRecordRead,
    IPStatsRead,
)
from app.admin.services.ip_intelligence import IPIntelligenceService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-ip-intelligence"])


@router.get("/ip-intelligence", response_model=list[IPRecordRead])
async def admin_list_ips(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    min_risk: int = Query(default=0, ge=0, le=100),
    is_banned: bool | None = Query(default=None),
    country: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[IPRecordRead]:
    service = IPIntelligenceService(db)
    ips = await service.list_ips(limit=limit, offset=offset, min_risk=min_risk, is_banned=is_banned, country=country)
    return [
        IPRecordRead(
            id=str(ip.id) if ip.id else None,
            ip_address=ip.ip_address,
            country=ip.country,
            city=ip.city,
            region=ip.region,
            latitude=float(ip.latitude) if ip.latitude else None,
            longitude=float(ip.longitude) if ip.longitude else None,
            asn=ip.asn,
            isp=ip.isp,
            is_vpn=ip.is_vpn,
            is_proxy=ip.is_proxy,
            is_tor=ip.is_tor,
            total_requests=ip.total_requests,
            failed_requests=ip.failed_requests,
            accounts_created=ip.accounts_created,
            api_keys_generated=ip.api_keys_generated,
            risk_score=ip.risk_score,
            is_banned=ip.is_banned,
            ban_type=ip.ban_type,
            ban_reason=ip.ban_reason,
            ban_expires_at=ip.ban_expires_at.isoformat() if ip.ban_expires_at else None,
            first_seen=ip.first_seen.isoformat() if ip.first_seen else "",
            last_seen=ip.last_seen.isoformat() if ip.last_seen else "",
        )
        for ip in ips
    ]


@router.get("/ip-intelligence/{ip_address}", response_model=IPStatsRead)
async def admin_get_ip(
    ip_address: str,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_READ)),
    db: AsyncSession = Depends(get_session),
) -> IPStatsRead:
    service = IPIntelligenceService(db)
    stats = await service.get_ip_stats(ip_address)
    return IPStatsRead(**stats)


@router.post("/ip-intelligence/{ip_address}/ban")
async def admin_ban_ip(
    ip_address: str,
    body: IPBanRequest,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = IPIntelligenceService(db)
    await service.ban_ip(ip_address, ban_type=body.ban_type, reason=body.reason, duration_hours=body.duration_hours)
    await db.commit()
    return {"message": f"IP {ip_address} banned"}


@router.post("/ip-intelligence/{ip_address}/unban")
async def admin_unban_ip(
    ip_address: str,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = IPIntelligenceService(db)
    await service.unban_ip(ip_address)
    await db.commit()
    return {"message": f"IP {ip_address} unbanned"}


@router.post("/ip-intelligence/{ip_address}/whitelist")
async def admin_whitelist_ip(
    ip_address: str,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = IPIntelligenceService(db)
    await service.whitelist_ip(ip_address)
    await db.commit()
    return {"message": f"IP {ip_address} whitelisted"}


@router.post("/ip-intelligence/{ip_address}/blacklist")
async def admin_blacklist_ip(
    ip_address: str,
    body: IPActionRequest | None = None,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = IPIntelligenceService(db)
    await service.blacklist_ip(ip_address, body.reason if body else None)
    await db.commit()
    return {"message": f"IP {ip_address} blacklisted"}


@router.post("/ip-intelligence/{ip_address}/rate-limit")
async def admin_rate_limit_ip(
    ip_address: str,
    body: IPActionRequest,
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = IPIntelligenceService(db)
    await service.rate_limit_ip(ip_address, limit=body.action.count() if isinstance(body.action, int) else 100)
    return {"message": f"IP {ip_address} rate limited"}


@router.get("/ip-intelligence/top/risk", response_model=list[IPRecordRead])
async def admin_top_ips_by_risk(
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AdminContext = Depends(require_permission(Permission.IP_INTELLIGENCE_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[IPRecordRead]:
    service = IPIntelligenceService(db)
    ips = await service.get_top_ips_by_risk(limit=limit)
    return [
        IPRecordRead(
            id=str(ip.id) if ip.id else None,
            ip_address=ip.ip_address,
            country=ip.country,
            city=ip.city,
            region=ip.region,
            latitude=float(ip.latitude) if ip.latitude else None,
            longitude=float(ip.longitude) if ip.longitude else None,
            asn=ip.asn,
            isp=ip.isp,
            is_vpn=ip.is_vpn,
            is_proxy=ip.is_proxy,
            is_tor=ip.is_tor,
            total_requests=ip.total_requests,
            failed_requests=ip.failed_requests,
            accounts_created=ip.accounts_created,
            api_keys_generated=ip.api_keys_generated,
            risk_score=ip.risk_score,
            is_banned=ip.is_banned,
            ban_type=ip.ban_type,
            ban_reason=ip.ban_reason,
            ban_expires_at=ip.ban_expires_at.isoformat() if ip.ban_expires_at else None,
            first_seen=ip.first_seen.isoformat() if ip.first_seen else "",
            last_seen=ip.last_seen.isoformat() if ip.last_seen else "",
        )
        for ip in ips
    ]
