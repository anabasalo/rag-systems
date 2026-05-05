"""Append-only structured query log.

One JSON object per line, written to ``settings.query_log_path``. The
schema is:

    {
      "ts":         ISO-8601 UTC timestamp,
      "endpoint":   "/query" | "/compare" | "/evaluate",
      "status":     "ok" | "error" | "declined" | "partial",
      "collection": <str>,
      "strategy":   <str | null>,
      "question":   <str | null>,
      "n_sources":  <int | null>,
      "latency_ms": <int | null>,
      "tokens":     {"prompt": <int|null>, "completion": <int|null>} | null,
      "error":      <str | null>,
      "extra":      <object>  -- endpoint-specific overflow
    }

The logger is safe to share across threads and is intentionally simple
(no async, no buffering): JSON-line writes are atomic on POSIX up to
PIPE_BUF, which is more than enough for our entries.

We cap the file at ``max_entries`` (default 10 000). On overflow we
rewrite, keeping the last half. This is O(N) on the rare overflow
event, O(1) per normal write. Production systems would use logrotate
or a real log pipeline; for a study project this stays self-contained.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class QueryLogger:
    """Append-only JSONL logger with a soft cap on size."""

    def __init__(self, path: str | Path, max_entries: int = 10_000) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        endpoint: str,
        status: str = "ok",
        collection: str | None = None,
        strategy: str | None = None,
        question: str | None = None,
        n_sources: int | None = None,
        latency_ms: int | None = None,
        tokens: dict | None = None,
        error: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Append one structured entry."""
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "endpoint": endpoint,
            "status": status,
            "collection": collection,
            "strategy": strategy,
            "question": question,
            "n_sources": n_sources,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "error": error,
            "extra": extra or {},
        }
        line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)

        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._maybe_truncate()

    def tail(self, limit: int = 50) -> list[dict]:
        """Return the last ``limit`` entries, newest last.

        Malformed lines (e.g. partial writes after a crash) are skipped.
        """
        if limit <= 0:
            return []
        if not self._path.exists():
            return []
        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        out: list[dict] = []
        for raw in lines[-limit:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out

    def _maybe_truncate(self) -> None:
        """Keep the last ``max_entries // 2`` lines if we exceed the cap."""
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return
        # Cheap fast path: small files never overflow.
        if size < 64 * 1024:
            return
        lines = self._path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self._max_entries:
            return
        keep = self._max_entries // 2
        kept = lines[-keep:]
        self._path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def iter_records(path: str | Path) -> Iterable[dict]:
    """Stream records from a JSONL log file. Used by tests and offline tools."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue
