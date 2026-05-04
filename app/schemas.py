"""Pydantic models for API requests and responses.

The shapes here are the ones documented in
`docs/00-design/05-api-contract.md`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ChromaDB collection name rules: 3-63 chars, [a-zA-Z0-9._-], must start
# and end with an alphanumeric. We surface this as a 422 from our API
# rather than letting Chroma's error bubble out.
COLLECTION_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,61}[a-zA-Z0-9]$"


class IngestResponse(BaseModel):
    doc_id: str
    doc_name: str
    collection: str
    chunks_written: int
    uploaded_at: str


class CollectionInfo(BaseModel):
    name: str
    doc_count: int
    chunk_count: int


class CollectionListResponse(BaseModel):
    collections: list[CollectionInfo]


class DocInfo(BaseModel):
    doc_name: str
    chunks: int
    uploaded_at: str


class DocListResponse(BaseModel):
    collection: str
    docs: list[DocInfo]


class DocFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_name: list[str] | None = None
    tags: list[str] | None = None


RetrievalStrategy = Literal["basic", "improved"]


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    collection: str = Field(..., pattern=COLLECTION_NAME_PATTERN)
    doc_filter: DocFilter | None = None
    strategy: RetrievalStrategy = "basic"
    k: int | None = Field(default=None, ge=1, le=50)


class CompareRequest(BaseModel):
    """Run both strategies on the same question. ``strategy`` is ignored."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    collection: str = Field(..., pattern=COLLECTION_NAME_PATTERN)
    doc_filter: DocFilter | None = None
    k: int | None = Field(default=None, ge=1, le=50)


class SourceChunk(BaseModel):
    chunk_id: str
    doc_name: str
    chunk_index: int
    score: float
    text: str


class TokenUsage(BaseModel):
    prompt: int | None = None
    completion: int | None = None


class QueryResponse(BaseModel):
    answer: str
    collection: str
    strategy: str
    sources: list[SourceChunk]
    latency_ms: int
    tokens: TokenUsage | None = None


class StrategyResult(BaseModel):
    """One side of a /compare response — same payload as a /query, minus
    the redundant ``collection`` (the parent envelope carries it)."""

    answer: str
    strategy: str
    sources: list[SourceChunk]
    latency_ms: int
    tokens: TokenUsage | None = None


class CompareResponse(BaseModel):
    question: str
    collection: str
    basic: StrategyResult
    improved: StrategyResult


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict = Field(default_factory=dict)
