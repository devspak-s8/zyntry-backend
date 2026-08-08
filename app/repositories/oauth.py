from __future__ import annotations

from app.models.oauth import OAuthConnection, OAuthProvider, OAuthState
from app.repositories.base import BaseRepository


class OAuthProviderRepository(BaseRepository[OAuthProvider]):
    model = OAuthProvider


class OAuthConnectionRepository(BaseRepository[OAuthConnection]):
    model = OAuthConnection


class OAuthStateRepository(BaseRepository[OAuthState]):
    model = OAuthState
