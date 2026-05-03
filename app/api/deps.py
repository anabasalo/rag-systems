"""FastAPI dependency providers.

The vector store, embedder, and generator are process singletons so we
do not re-load the embedding model on every request. Tests override
these via ``app.dependency_overrides`` to inject fakes.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.core.embedders import Embedder, SentenceTransformerEmbedder
from app.core.generation import Generator, GroqGenerator
from app.db.vector_store import VectorStore


@lru_cache(maxsize=1)
def _vector_store_singleton() -> VectorStore:
    settings = get_settings()
    return VectorStore(persist_dir=settings.chroma_persist_dir)


@lru_cache(maxsize=1)
def _embedder_singleton() -> Embedder:
    settings = get_settings()
    return SentenceTransformerEmbedder(settings.embed_model)


@lru_cache(maxsize=1)
def _generator_singleton() -> Generator:
    settings = get_settings()
    return GroqGenerator(api_key=settings.groq_api_key, model=settings.llm_model)


def get_settings_dep() -> Settings:
    return get_settings()


def get_vector_store() -> VectorStore:
    return _vector_store_singleton()


def get_embedder() -> Embedder:
    return _embedder_singleton()


def get_generator() -> Generator:
    return _generator_singleton()
