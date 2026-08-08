from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    FingerprintDetailRead,
    FingerprintFlagRequest,
    FingerprintTrustUpdate,
)
from app.admin.services.fingerprinting import FingerprintingService
from app.core.database import get_session

router = APIRouter(prefix="/admin", tags=["admin-fingerprints"])


@router.get("/fingerprints", response_model=list[FingerprintDetailRead])
async def admin_list_fingerprints(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    min_risk: int = Query(default=0, ge=0, le=100),
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[FingerprintDetailRead]:
    service = FingerprintingService(db)
    fingerprints = await service.list_flagged(min_risk=min_risk, limit=limit, offset=offset)
    return [
        FingerprintDetailRead(
            id=str(fp.id) if fp.id else None,
            user_id=str(fp.user_id) if fp.user_id else None,
            organization_id=str(fp.organization_id) if fp.organization_id else None,
            fingerprint_hash=fp.fingerprint_hash,
            browser=fp.browser,
            os_name=fp.os_name,
            device=fp.device,
            timezone=fp.timezone,
            language=fp.language,
            screen_resolution=fp.screen_resolution,
            canvas_fingerprint=fp.canvas_fingerprint,
            webgl_fingerprint=fp.webgl_fingerprint,
            tls_signature=fp.tls_signature,
            is_trusted=fp.is_trusted,
            risk_score=fp.risk_score,
            first_seen=fp.first_seen.isoformat() if fp.first_seen else "",
            last_seen=fp.last_seen.isoformat() if fp.last_seen else "",
            metadata_=fp.metadata_,
        )
        for fp in fingerprints
    ]


@router.get("/fingerprints/{fingerprint_hash}", response_model=FingerprintDetailRead)
async def admin_get_fingerprint(
    fingerprint_hash: str,
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> FingerprintDetailRead:
    service = FingerprintingService(db)
    fp = await service.get_or_create_fingerprint(fingerprint_hash)
    return FingerprintDetailRead(
        id=str(fp.id) if fp.id else None,
        user_id=str(fp.user_id) if fp.user_id else None,
        organization_id=str(fp.organization_id) if fp.organization_id else None,
        fingerprint_hash=fp.fingerprint_hash,
        browser=fp.browser,
        os_name=fp.os_name,
        device=fp.device,
        timezone=fp.timezone,
        language=fp.language,
        screen_resolution=fp.screen_resolution,
        canvas_fingerprint=fp.canvas_fingerprint,
        webgl_fingerprint=fp.webgl_fingerprint,
        tls_signature=fp.tls_signature,
        is_trusted=fp.is_trusted,
        risk_score=fp.risk_score,
        first_seen=fp.first_seen.isoformat() if fp.first_seen else "",
        last_seen=fp.last_seen.isoformat() if fp.last_seen else "",
        metadata_=fp.metadata_,
    )


@router.get("/fingerprints/user/{user_id}", response_model=list[FingerprintDetailRead])
async def admin_user_fingerprints(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[FingerprintDetailRead]:
    service = FingerprintingService(db)
    fingerprints = await service.get_user_fingerprints(user_id, limit=limit, offset=offset)
    return [
        FingerprintDetailRead(
            id=str(fp.id) if fp.id else None,
            user_id=str(fp.user_id) if fp.user_id else None,
            organization_id=str(fp.organization_id) if fp.organization_id else None,
            fingerprint_hash=fp.fingerprint_hash,
            browser=fp.browser,
            os_name=fp.os_name,
            device=fp.device,
            timezone=fp.timezone,
            language=fp.language,
            screen_resolution=fp.screen_resolution,
            canvas_fingerprint=fp.canvas_fingerprint,
            webgl_fingerprint=fp.webgl_fingerprint,
            tls_signature=fp.tls_signature,
            is_trusted=fp.is_trusted,
            risk_score=fp.risk_score,
            first_seen=fp.first_seen.isoformat() if fp.first_seen else "",
            last_seen=fp.last_seen.isoformat() if fp.last_seen else "",
            metadata_=fp.metadata_,
        )
        for fp in fingerprints
    ]


@router.post("/fingerprints/{fingerprint_hash}/trust")
async def admin_update_fingerprint_trust(
    fingerprint_hash: str,
    body: FingerprintTrustUpdate,
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = FingerprintingService(db)
    await service.update_fingerprint_trust(fingerprint_hash, body.is_trusted)
    return {"message": "Fingerprint trust updated"}


@router.post("/fingerprints/{fingerprint_hash}/flag")
async def admin_flag_fingerprint(
    fingerprint_hash: str,
    body: FingerprintFlagRequest,
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = FingerprintingService(db)
    await service.flag_fingerprint(fingerprint_hash, body.risk_score)
    return {"message": "Fingerprint flagged"}


@router.get("/fingerprints/flagged", response_model=list[FingerprintDetailRead])
async def admin_flagged_fingerprints(
    min_risk: int = Query(default=50, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.FINGERPRINTS_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[FingerprintDetailRead]:
    service = FingerprintingService(db)
    fingerprints = await service.list_flagged(min_risk=min_risk, limit=limit, offset=offset)
    return [
        FingerprintDetailRead(
            id=str(fp.id) if fp.id else None,
            user_id=str(fp.user_id) if fp.user_id else None,
            organization_id=str(fp.organization_id) if fp.organization_id else None,
            fingerprint_hash=fp.fingerprint_hash,
            browser=fp.browser,
            os_name=fp.os_name,
            device=fp.device,
            timezone=fp.timezone,
            language=fp.language,
            screen_resolution=fp.screen_resolution,
            canvas_fingerprint=fp.canvas_fingerprint,
            webgl_fingerprint=fp.webgl_fingerprint,
            tls_signature=fp.tls_signature,
            is_trusted=fp.is_trusted,
            risk_score=fp.risk_score,
            first_seen=fp.first_seen.isoformat() if fp.first_seen else "",
            last_seen=fp.last_seen.isoformat() if fp.last_seen else "",
            metadata_=fp.metadata_,
        )
        for fp in fingerprints
    ]