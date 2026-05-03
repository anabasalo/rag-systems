"""Application settings loaded from environment / .env.

Centralized so every other module reads configuration from one typed object.
See `docs/00-design/03-architecture.md` (Cross-cutting concerns).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    groq_api_key: str = Field(default="", description="Groq API key (Phase 2+).")
    llm_model: str = Field(default="llama3-8b-8192")

    embed_model: str = Field(default="all-MiniLM-L6-v2")

    chroma_persist_dir: Path = Field(default=Path("./data/chroma"))

    top_k: int = Field(default=5, ge=1, le=50)
    similarity_floor: float = Field(default=0.2, ge=0.0, le=1.0)

    chunk_size: int = Field(default=2000, ge=100)
    chunk_overlap: int = Field(default=200, ge=0)

    query_log_path: Path = Field(default=Path("./logs/queries.jsonl"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
