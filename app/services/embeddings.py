from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

import httpx

from app.services.embedding_cache import EmbeddingCacheService


class EmbeddingMetadata:
    def __init__(
        self,
        document_id: str,
        chunk_id: str,
        source: str,
        content_hash: str,
        embedding_version: str = "1",
    ) -> None:
        self.document_id = document_id
        self.chunk_id = chunk_id
        self.source = source
        self.content_hash = content_hash
        self.embedding_version = embedding_version

    def to_dict(self) -> dict[str, str]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "source": self.source,
            "content_hash": self.content_hash,
            "embedding_version": self.embedding_version,
        }


class BaseEmbeddingProvider(ABC):
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=5.0,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=60.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._dimensions = 1536 if "small" in model else 3072

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        response = await self._http_client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


class VoyageEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, model: str = "voyage-3") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._dimensions = 1024

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "voyage"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        response = await self._http_client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


class CohereEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, model: str = "embed-english-v3.0") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._dimensions = 1024

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "cohere"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        response = await self._http_client.post(
            "https://api.cohere.ai/v1/embed",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "texts": texts, "input_type": "search_document"},
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"]


class GoogleEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, model: str = "text-embedding-004") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._dimensions = 768

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        response = await self._http_client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:batchEmbedContents?key={self._api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "requests": [
                    {"model": f"models/{self._model}", "content": {"parts": [{"text": text}]}}
                    for text in texts
                ]
            },
        )
        response.raise_for_status()
        data = response.json()
        return [item["values"] for item in data.get("embeddings", [])]


class AzureOpenAIEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, endpoint: str, deployment: str, api_version: str = "2024-06-01") -> None:
        super().__init__()
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version
        self._dimensions = 1536

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return self._deployment

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        url = f"{self._endpoint}/openai/deployments/{self._deployment}/embeddings?api-version={self._api_version}"
        response = await self._http_client.post(
            url,
            headers={
                "api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json={"input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


class BedrockEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, aws_access_key: str, aws_secret_key: str, region: str, model_id: str = "amazon.titan-embed-text-v1") -> None:
        super().__init__()
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key
        self._region = region
        self._model_id = model_id
        self._dimensions = 1536

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "bedrock"

    @property
    def model_name(self) -> str:
        return self._model_id

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            aws_access_key_id=self._aws_access_key,
            aws_secret_access_key=self._aws_secret_key,
            config=Config(signature_version="v4"),
        )
        results = []
        for text in texts:
            body = {"inputText": text}
            response = client.invoke_model(
                modelId=self._model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(response["body"].read())
            results.append(payload.get("embedding", []))
        return results


class OpenRouterEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, api_key: str, model: str = "openai/text-embedding-3-small") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._dimensions = 1536 if "small" in model else 3072

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], metadata: list[EmbeddingMetadata], use_cache: bool = True) -> list[list[float]]:
        response = await self._http_client.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


def get_embedding_provider(provider_name: str, api_key: str, model: str, **kwargs) -> BaseEmbeddingProvider:
    providers = {
        "openai": OpenAIEmbeddingProvider,
        "voyage": VoyageEmbeddingProvider,
        "cohere": CohereEmbeddingProvider,
        "google": GoogleEmbeddingProvider,
        "azure_openai": AzureOpenAIEmbeddingProvider,
        "bedrock": BedrockEmbeddingProvider,
        "openrouter": OpenRouterEmbeddingProvider,
    }
    provider_cls = providers.get(provider_name.lower())
    if not provider_cls:
        raise ValueError(f"Unsupported embedding provider: {provider_name}")
    if provider_name.lower() == "azure_openai":
        return provider_cls(
            api_key=api_key,
            endpoint=kwargs.get("endpoint", ""),
            deployment=model,
            api_version=kwargs.get("api_version", "2024-06-01"),
        )
    if provider_name.lower() == "bedrock":
        return provider_cls(
            aws_access_key=kwargs.get("aws_access_key", ""),
            aws_secret_key=kwargs.get("aws_secret_key", ""),
            region=kwargs.get("region", "us-east-1"),
            model_id=model,
        )
    return provider_cls(api_key=api_key, model=model)


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def embed_with_cache(
    provider: BaseEmbeddingProvider,
    texts: list[str],
    metadata: list[EmbeddingMetadata],
    project_id: UUID,
    cache_service: EmbeddingCacheService,
    use_cache: bool = True,
    batch_size: int = 100,
    max_concurrency: int = 4,
) -> list[list[float]]:
    if not use_cache or not texts:
        return await provider.embed(texts, metadata, use_cache=False)

    cached_results: dict[int, list[float]] = {}
    misses: list[str] = []
    miss_indices: list[int] = []

    for i, (text, meta) in enumerate(zip(texts, metadata, strict=True)):
        cached = await cache_service.get(
            project_id=project_id,
            content_hash=meta.content_hash,
            embedding_version=meta.embedding_version,
            embedding_model=provider.model_name,
            provider=provider.provider_name,
        )
        if cached is not None:
            cached_results[i] = cached
        else:
            misses.append(text)
            miss_indices.append(i)

    if misses:
        miss_metadatas = [metadata[i] for i in miss_indices]

        if len(misses) <= batch_size:
            miss_results = await provider.embed(misses, miss_metadatas, use_cache=False)
            for idx, result in zip(miss_indices, miss_results, strict=True):
                cached_results[idx] = result
                meta = metadata[idx]
                await cache_service.set(
                    project_id=project_id,
                    content_hash=meta.content_hash,
                    embedding_version=meta.embedding_version,
                    embedding_model=provider.model_name,
                    provider=provider.provider_name,
                    vector=result,
                    dimensions=len(result),
                )
        else:
            miss_batches = [
                (misses[i : i + batch_size], miss_metadatas[i : i + batch_size], miss_indices[i : i + batch_size])
                for i in range(0, len(misses), batch_size)
            ]

            semaphore = asyncio.Semaphore(max_concurrency)

            async def _process_batch(
                batch_texts: list[str],
                batch_metas: list[EmbeddingMetadata],
                batch_indices: list[int],
            ) -> tuple[list[float], list[int]]:
                async with semaphore:
                    results = await provider.embed(batch_texts, batch_metas, use_cache=False)
                    return results, batch_indices

            batch_tasks = [
                _process_batch(bt, bm, bi)
                for bt, bm, bi in miss_batches
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for batch_result in batch_results:
                if isinstance(batch_result, Exception):
                    raise batch_result
                batch_embeddings, batch_indices = batch_result
                for idx, result in zip(batch_indices, batch_embeddings, strict=True):
                    cached_results[idx] = result
                    meta = metadata[idx]
                    await cache_service.set(
                        project_id=project_id,
                        content_hash=meta.content_hash,
                        embedding_version=meta.embedding_version,
                        embedding_model=provider.model_name,
                        provider=provider.provider_name,
                        vector=result,
                        dimensions=len(result),
                    )

    return [cached_results[i] for i in range(len(texts))]