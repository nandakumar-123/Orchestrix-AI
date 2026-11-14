import asyncio
import hashlib
import logging
import math
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("orchestrix.embedding")

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384


class BaseEmbeddingProvider(ABC):
    """Abstract base class for provider-independent text and code embeddings."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the underlying embedding model."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimension of the embedding vector."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Version string of the embedding configuration."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text documents."""
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Embed a single natural language search query."""
        pass


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic embedding provider for unit tests and offline environments.
    Produces unit-normalized 384-dimensional vectors without downloading models.
    """

    def __init__(
        self,
        dimension: int = DEFAULT_EMBEDDING_DIM,
        model_name: str = "mock-minilm-l6-v2",
    ) -> None:
        self._dim = dimension
        self._model = model_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def version(self) -> str:
        return "1.0.0-mock"

    def _generate_vector(self, text: str) -> list[float]:
        """Generate deterministic pseudo-random unit-normalized vector from text hash."""
        vec: list[float] = []
        # Use multiple hash seeds to populate all dimensions
        for i in range(self._dim):
            seed_str = f"{text}:{i}:{self._dim}"
            h_val = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8], 16)
            # Center around 0 (-1.0 to 1.0)
            norm_val = ((h_val % 10000) / 5000.0) - 1.0
            vec.append(norm_val)

        # Normalize to unit length for cosine similarity
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._generate_vector(query)


class FastEmbedProvider(BaseEmbeddingProvider):
    """
    Production-grade CPU-only embedding provider powered by FastEmbed and ONNX Runtime.
    Runs locally on Windows 11 with zero CUDA/GPU dependencies and conservative memory footprint.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        threads: int = 1,
        batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._threads = threads
        self._batch_size = batch_size
        self._model: Any = None
        self._lock = asyncio.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info(
                "Initializing FastEmbed model: %s (threads=%d)", self._model_name, self._threads
            )
            self._model = TextEmbedding(
                model_name=self._model_name,
                threads=self._threads,
            )
        return self._model

    @property
    def provider_name(self) -> str:
        return "fastembed"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return DEFAULT_EMBEDDING_DIM

    @property
    def version(self) -> str:
        return "fastembed-0.9.1"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        async with self._lock:
            # Run CPU-bound ONNX model inference in default executor thread to avoid blocking event loop
            loop = asyncio.get_running_loop()

            def _infer() -> list[list[float]]:
                model = self._get_model()
                results: list[list[float]] = []
                # FastEmbed returns a generator of numpy arrays
                embeddings_gen = model.embed(texts, batch_size=self._batch_size)
                for emb in embeddings_gen:
                    results.append(emb.tolist())
                return results

            return await loop.run_in_executor(None, _infer)

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed_texts([query])
        return results[0] if results else [0.0] * self.dimension


# Provider Singleton Cache
_CACHED_PROVIDER: BaseEmbeddingProvider | None = None


def get_embedding_provider(force_provider: str | None = None) -> BaseEmbeddingProvider:
    """
    Factory resolving the active embedding provider.
    Reads environment variable ORCHESTRIX_EMBEDDING_PROVIDER (defaults to fastembed, falls back to mock).
    """
    global _CACHED_PROVIDER

    provider_type = (
        force_provider or os.getenv("ORCHESTRIX_EMBEDDING_PROVIDER", "fastembed").lower()
    )

    if _CACHED_PROVIDER is not None and (
        force_provider is None or _CACHED_PROVIDER.provider_name == provider_type
    ):
        return _CACHED_PROVIDER

    provider: BaseEmbeddingProvider
    if provider_type == "mock":
        provider = MockEmbeddingProvider()
    else:
        try:
            provider = FastEmbedProvider()
        except Exception as exc:
            logger.warning(
                "Failed to initialize FastEmbedProvider, falling back to MockEmbeddingProvider: %s",
                exc,
            )
            provider = MockEmbeddingProvider()

    if force_provider is None:
        _CACHED_PROVIDER = provider

    return provider


def set_cached_embedding_provider(provider: BaseEmbeddingProvider | None) -> None:
    """Explicitly override or reset cached embedding provider (e.g. for testing)."""
    global _CACHED_PROVIDER
    _CACHED_PROVIDER = provider
