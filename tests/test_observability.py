"""Phase 5 observability tests.

Covers ``QueryLogger`` directly: append shape, tail ordering, malformed
line tolerance, and the size cap.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.observability.query_log import QueryLogger, iter_records


def test_record_writes_one_jsonl_line_with_expected_shape(tmp_path: Path):
    log = QueryLogger(path=tmp_path / "q.jsonl")
    log.record(
        endpoint="/query",
        collection="k8s",
        strategy="basic",
        question="How does HPA work?",
        n_sources=3,
        latency_ms=420,
        tokens={"prompt": 700, "completion": 50},
    )

    raw = (tmp_path / "q.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1
    entry = json.loads(raw[0])
    assert entry["endpoint"] == "/query"
    assert entry["status"] == "ok"
    assert entry["collection"] == "k8s"
    assert entry["strategy"] == "basic"
    assert entry["question"] == "How does HPA work?"
    assert entry["n_sources"] == 3
    assert entry["latency_ms"] == 420
    assert entry["tokens"] == {"prompt": 700, "completion": 50}
    assert entry["extra"] == {}
    assert entry["error"] is None
    # ts is ISO-8601 with timezone
    assert entry["ts"].endswith("+00:00") or entry["ts"].endswith("Z")


def test_record_supports_extra_payload(tmp_path: Path):
    log = QueryLogger(path=tmp_path / "q.jsonl")
    log.record(endpoint="/compare", extra={"basic": {"n_sources": 2}})
    entry = log.tail(1)[0]
    assert entry["extra"] == {"basic": {"n_sources": 2}}


def test_tail_returns_newest_last(tmp_path: Path):
    log = QueryLogger(path=tmp_path / "q.jsonl")
    for i in range(5):
        log.record(endpoint="/query", question=f"q{i}")
    tail = log.tail(limit=3)
    assert len(tail) == 3
    assert [e["question"] for e in tail] == ["q2", "q3", "q4"]


def test_tail_empty_when_log_does_not_exist(tmp_path: Path):
    log = QueryLogger(path=tmp_path / "missing.jsonl")
    # Don't write anything; the parent dir was created on init but file doesn't exist yet.
    assert log.tail(10) == []


def test_tail_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "q.jsonl"
    p.write_text(
        '{"endpoint":"/query","status":"ok","ts":"x"}\nnot-json\n{"endpoint":"/health","status":"ok","ts":"y"}\n',
        encoding="utf-8",
    )
    log = QueryLogger(path=p)
    entries = log.tail(10)
    assert [e["endpoint"] for e in entries] == ["/query", "/health"]


def test_tail_limit_zero_returns_empty(tmp_path: Path):
    log = QueryLogger(path=tmp_path / "q.jsonl")
    log.record(endpoint="/query")
    assert log.tail(0) == []


def test_size_cap_keeps_last_half(tmp_path: Path):
    """Once the file exceeds 64 KB AND the entry count exceeds the cap,
    the logger rewrites it to the last ``max_entries // 2`` lines."""
    log = QueryLogger(path=tmp_path / "q.jsonl", max_entries=10)
    big_payload = "x" * 4000  # each entry well over 4 KB
    for i in range(60):
        log.record(endpoint="/query", question=f"q{i}", extra={"blob": big_payload})

    entries = log.tail(limit=500)
    # After truncation we keep at most max_entries // 2 = 5.
    assert len(entries) <= 5
    # And the entries we keep are the most recent ones.
    last_seen = [int(e["question"][1:]) for e in entries]
    assert last_seen == sorted(last_seen)
    assert max(last_seen) == 59


def test_iter_records_streams_valid_lines(tmp_path: Path):
    p = tmp_path / "q.jsonl"
    p.write_text(
        '{"endpoint":"/query","status":"ok","ts":"x"}\n{"endpoint":"/health","status":"ok","ts":"y"}\n',
        encoding="utf-8",
    )
    items = list(iter_records(p))
    assert [i["endpoint"] for i in items] == ["/query", "/health"]


def test_iter_records_returns_nothing_when_path_missing(tmp_path: Path):
    items = list(iter_records(tmp_path / "missing.jsonl"))
    assert items == []
