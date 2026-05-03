"""Phase 1 unit tests: chunking, ingestion, metadata, isolation, idempotence."""

from __future__ import annotations

import pytest

from app.core.ingestion import (
    IngestionError,
    chunk_text,
    ingest,
)
from app.db.vector_store import VectorStore

# ---------- chunk_text ----------


def test_chunk_text_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_short_text_returns_single_chunk():
    text = "A short paragraph that is well under the target size."
    chunks = chunk_text(text, target_size=2000, overlap=200)
    assert chunks == [text]


def test_chunk_text_long_text_splits_into_multiple():
    sentence = "This is a sentence. " * 200  # ~4000 chars
    chunks = chunk_text(sentence, target_size=1000, overlap=100)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) > 0


def test_chunk_text_chunks_have_overlap_when_no_natural_boundary():
    # 5000 chars, no sentence/paragraph/newline boundaries.
    text = "abcdefghij" * 500
    chunks = chunk_text(text, target_size=1000, overlap=100)
    assert len(chunks) >= 4
    for i in range(len(chunks) - 1):
        tail = chunks[i][-100:]
        assert chunks[i + 1].startswith(tail), f"overlap broken between chunk {i} and {i + 1}"


def test_chunk_text_prefers_paragraph_boundary():
    para_a = "Apples. " * 150  # ~1200 chars
    para_b = "Bananas. " * 150  # ~1350 chars
    text = para_a.strip() + "\n\n" + para_b.strip()
    chunks = chunk_text(text, target_size=1300, overlap=100)
    assert len(chunks) >= 2
    # First chunk should be dominated by Apples (paragraph 1).
    assert chunks[0].count("Apples") > chunks[0].count("Bananas")


def test_chunk_text_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_text("anything", target_size=100, overlap=100)
    with pytest.raises(ValueError):
        chunk_text("anything", target_size=100, overlap=-1)


# ---------- ingest ----------


def test_ingest_md_writes_chunks(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    path = make_doc("hello.md", "Hello world. " * 200)

    result = ingest(
        file_path=path,
        collection="test",
        vector_store=store,
        embedder=fake_embedder,
        tags=["greeting", "hello"],
    )

    assert result.doc_name == "hello.md"
    assert result.collection == "test"
    assert result.source_type == "markdown"
    assert result.chunks_written > 0
    assert len(result.uploaded_at) > 0


def test_ingest_propagates_metadata(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    path = make_doc("hello.md", "Hello world. " * 200)
    result = ingest(
        file_path=path,
        collection="test",
        vector_store=store,
        embedder=fake_embedder,
        tags=["greeting", "hello"],
    )

    embedding = fake_embedder.embed(["Hello world"])[0]
    chunks = store.query("test", embedding, k=10)
    assert chunks, "expected at least one chunk to come back"

    seen_indices = set()
    for chunk in chunks:
        assert chunk.metadata["doc_id"] == result.doc_id
        assert chunk.metadata["doc_name"] == "hello.md"
        assert chunk.metadata["source_type"] == "markdown"
        assert chunk.metadata["tags"] == "greeting,hello"
        assert chunk.metadata["uploaded_at"] == result.uploaded_at
        idx = int(chunk.metadata["chunk_index"])
        assert 0 <= idx < result.chunks_written
        seen_indices.add(idx)
    assert len(seen_indices) >= 1


def test_ingest_unknown_extension_raises(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    path = make_doc("notes.docx", "irrelevant")
    with pytest.raises(IngestionError):
        ingest(
            file_path=path,
            collection="test",
            vector_store=store,
            embedder=fake_embedder,
        )


def test_ingest_missing_file_raises(tmp_chroma_dir, fake_embedder, tmp_path):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    with pytest.raises(IngestionError):
        ingest(
            file_path=tmp_path / "does-not-exist.md",
            collection="test",
            vector_store=store,
            embedder=fake_embedder,
        )


def test_ingest_empty_file_raises(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    path = make_doc("empty.md", "   \n   \n  ")
    with pytest.raises(IngestionError):
        ingest(
            file_path=path,
            collection="test",
            vector_store=store,
            embedder=fake_embedder,
        )


def test_ingest_multi_doc_same_collection(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    p1 = make_doc("first.md", "First doc text. " * 100)
    p2 = make_doc("second.md", "Second doc text. " * 100)

    r1 = ingest(p1, "shared", store, fake_embedder)
    r2 = ingest(p2, "shared", store, fake_embedder)

    docs = store.list_docs("shared")
    names = {d.doc_name for d in docs}
    assert names == {"first.md", "second.md"}
    total = sum(d.chunks for d in docs)
    assert total == r1.chunks_written + r2.chunks_written


def test_ingest_collection_isolation(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    pa = make_doc("a.md", "Apple banana cherry. " * 100)
    pb = make_doc("b.md", "Xenon yttrium zirconium. " * 100)

    ingest(pa, "coll_a", store, fake_embedder)
    ingest(pb, "coll_b", store, fake_embedder)

    a_docs = {d.doc_name for d in store.list_docs("coll_a")}
    b_docs = {d.doc_name for d in store.list_docs("coll_b")}
    assert a_docs == {"a.md"}
    assert b_docs == {"b.md"}

    embedding = fake_embedder.embed(["banana"])[0]
    results = store.query("coll_a", embedding, k=10)
    assert results
    for r in results:
        assert r.doc_name == "a.md"


def test_ingest_reingest_replaces_chunks(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)

    path_v1 = make_doc("foo.md", "Original content. " * 100)
    r1 = ingest(path_v1, "test", store, fake_embedder)
    assert r1.chunks_written > 0

    path_v2 = make_doc("foo.md", "New content here. " * 50)
    r2 = ingest(path_v2, "test", store, fake_embedder)

    docs = store.list_docs("test")
    assert len(docs) == 1
    assert docs[0].doc_name == "foo.md"
    assert docs[0].chunks == r2.chunks_written

    embedding = fake_embedder.embed(["content"])[0]
    results = store.query("test", embedding, k=20)
    assert results
    for r in results:
        assert r.metadata["doc_id"] == r2.doc_id


def test_list_collections_reports_counts(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    p1 = make_doc("first.md", "alpha beta gamma. " * 100)
    p2 = make_doc("second.md", "delta epsilon zeta. " * 100)

    r1 = ingest(p1, "alpha", store, fake_embedder)
    r2 = ingest(p2, "beta", store, fake_embedder)

    summary = {c.name: c for c in store.list_collections()}
    assert "alpha" in summary
    assert "beta" in summary
    assert summary["alpha"].doc_count == 1
    assert summary["alpha"].chunk_count == r1.chunks_written
    assert summary["beta"].doc_count == 1
    assert summary["beta"].chunk_count == r2.chunks_written


def test_delete_doc_removes_only_target(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    p1 = make_doc("keep.md", "Keep this. " * 100)
    p2 = make_doc("drop.md", "Drop this. " * 100)
    ingest(p1, "test", store, fake_embedder)
    r2 = ingest(p2, "test", store, fake_embedder)

    removed = store.delete_doc("test", "drop.md")
    assert removed == r2.chunks_written

    remaining = {d.doc_name for d in store.list_docs("test")}
    assert remaining == {"keep.md"}


def test_query_unknown_collection_returns_empty(tmp_chroma_dir, fake_embedder):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    embedding = fake_embedder.embed(["anything"])[0]
    assert store.query("does-not-exist", embedding, k=5) == []
