from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.schemas.providers import ProviderConnectionCreate
from app.services.providers import ProviderService
from app.services.security.secrets import default_secret_manager


class ProviderRepo:
    def __init__(self):
        self.created = None

    async def get_by_provider(self, project_id, provider_name):
        return None

    async def create(self, **kwargs):
        self.created = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=None,
            updated_at=None,
            **kwargs,
        )
        return self.created


class Uow:
    def __init__(self):
        self.providers = ProviderRepo()
        self.session = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalars=lambda: SimpleNamespace(first=lambda: None)
                )
            )
        )

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_provider_connection_is_verified_and_encrypted():
    uow = Uow()
    service = ProviderService(uow)
    service._test_model_provider = AsyncMock(return_value=True)

    result = await service.connect(
        ProviderConnectionCreate(
            provider_name="openai",
            api_key="test-provider-secret",
            organization_id=str(uuid.uuid4()),
        )
    )

    assert result["status"] == "active"
    assert uow.providers.created.encrypted_api_key.startswith("ENCV1:")
    assert "test-provider-secret" not in uow.providers.created.encrypted_api_key
    assert default_secret_manager.decrypt(uow.providers.created.encrypted_api_key) == "test-provider-secret"


@pytest.mark.asyncio
async def test_provider_connection_rejects_invalid_credentials():
    uow = Uow()
    service = ProviderService(uow)
    service._test_model_provider = AsyncMock(return_value=False)

    with pytest.raises(ValueError, match="could not be verified"):
        await service.connect(
            ProviderConnectionCreate(
                provider_name="openai",
                api_key="invalid",
                organization_id=str(uuid.uuid4()),
            )
        )
