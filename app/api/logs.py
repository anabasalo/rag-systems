"""Tail the structured query log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_query_logger
from app.observability.query_log import QueryLogger
from app.schemas import LogEntry, LogsResponse

router = APIRouter(tags=["ops"])


@router.get("/logs", response_model=LogsResponse)
def logs_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    logger: QueryLogger = Depends(get_query_logger),
) -> LogsResponse:
    entries = logger.tail(limit=limit)
    return LogsResponse(
        limit=limit,
        entries=[LogEntry(**entry) for entry in entries],
    )
