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


class EvaluateItem(BaseModel):
    """One eval question. ``ground_truth`` is optional — some metrics
    (faithfulness, answer relevancy) work without it; others (context
    recall) need it."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    ground_truth: str | None = None


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(..., pattern=COLLECTION_NAME_PATTERN)
    strategy: RetrievalStrategy = "basic"
    items: list[EvaluateItem] = Field(..., min_length=1, max_length=50)
    k: int | None = Field(default=None, ge=1, le=50)


class EvaluateResultItem(BaseModel):
    question: str
    answer: str
    ground_truth: str | None = None
    retrieved_doc_names: list[str]
    metrics: dict[str, float | None]


class EvaluateResponse(BaseModel):
    collection: str
    strategy: str
    results: list[EvaluateResultItem]
    summary: dict[str, float | None]
    item_count: int
    answered_count: int
    declined_count: int


class HealthResponse(BaseModel):
    status: str
    version: str
    collections: int


class LogEntry(BaseModel):
    """One structured query-log line. Fields mirror ``QueryLogger.record``."""

    model_config = ConfigDict(extra="allow")

    ts: str
    endpoint: str
    status: str
    collection: str | None = None
    strategy: str | None = None
    question: str | None = None
    n_sources: int | None = None
    latency_ms: int | None = None
    tokens: dict | None = None
    error: str | None = None
    extra: dict = Field(default_factory=dict)


class LogsResponse(BaseModel):
    limit: int
    entries: list[LogEntry]


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict = Field(default_factory=dict)
