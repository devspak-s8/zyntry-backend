from __future__ import annotations

from sqlalchemy import select

from app.models.oauth import OAuthConnection, OAuthProvider, OAuthState
from app.repositories.base import BaseRepository


class OAuthProviderRepository(BaseRepository[OAuthProvider]):
    model = OAuthProvider

    async def get_by_name(self, name: str) -> OAuthProvider | None:
        stmt = select(OAuthProvider).where(OAuthProvider.name == name)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


class OAuthConnectionRepository(BaseRepository[OAuthConnection]):
    model = OAuthConnection


class OAuthStateRepository(BaseRepository[OAuthState]):
    model = OAuthState

    async def get_by_state(self, state: str) -> OAuthState | None:
        stmt = select(OAuthState).where(OAuthState.state == state)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
