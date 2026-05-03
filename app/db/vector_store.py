"""Thin ChromaDB wrapper.

This is the single place in the project that imports `chromadb`. Every
other module sees only the `VectorStore` class and the value objects
exposed below.

See ADR 0001 for the choice of ChromaDB and ADR 0005 for the
collections-plus-metadata scoping model that this module supports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import chromadb


@dataclass(frozen=True)
class CollectionSummary:
    name: str
    doc_count: int
    chunk_count: int


@dataclass(frozen=True)
class DocSummary:
    doc_name: str
    chunks: int
    uploaded_at: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_name: str
    chunk_index: int
    text: str
    score: float
    metadata: dict


# Cosine distance/similarity is a more intuitive measure than the L2 default
# and is what every retrieval/eval doc in this project assumes.
_HNSW_METADATA = {"hnsw:space": "cosine"}


class VectorStore:
    """High-level wrapper over ChromaDB persistent storage."""

    def __init__(self, persist_dir: str | Path) -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))

    @property
    def persist_dir(self) -> Path:
        return self._persist_dir

    # --- collection lifecycle ---

    def get_or_create_collection(self, name: str):
        """Return (or create) a collection configured for cosine similarity."""
        return self._client.get_or_create_collection(name=name, metadata=_HNSW_METADATA)

    def delete_collection(self, name: str) -> bool:
        """Delete a whole collection. Returns False if it did not exist."""
        try:
            self._client.delete_collection(name)
            return True
        except Exception:
            return False

    def collection_exists(self, name: str) -> bool:
        return self._get_collection_or_none(name) is not None

    def list_collections(self) -> list[CollectionSummary]:
        out: list[CollectionSummary] = []
        for entry in self._client.list_collections():
            coll_name = entry.name if hasattr(entry, "name") else str(entry)
            coll = self._get_collection_or_none(coll_name)
            if coll is None:
                continue
            chunk_count = coll.count()
            doc_count = self._distinct_doc_count(coll)
            out.append(
                CollectionSummary(name=coll_name, doc_count=doc_count, chunk_count=chunk_count)
            )
        return out

    def list_docs(self, collection: str) -> list[DocSummary]:
        coll = self._get_collection_or_none(collection)
        if coll is None:
            return []
        result = coll.get(include=["metadatas"])
        metas = result.get("metadatas") or []
        agg: dict[str, dict] = {}
        for meta in metas:
            doc_name = meta.get("doc_name", "")
            entry = agg.setdefault(doc_name, {"chunks": 0, "uploaded_at": ""})
            entry["chunks"] += 1
            ts = meta.get("uploaded_at", "")
            if ts > entry["uploaded_at"]:
                entry["uploaded_at"] = ts
        return [
            DocSummary(doc_name=name, chunks=v["chunks"], uploaded_at=v["uploaded_at"])
            for name, v in sorted(agg.items())
        ]

    # --- writes ---

    def add_chunks(
        self,
        collection: str,
        ids: Sequence[str],
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict],
    ) -> None:
        if not ids:
            return
        coll = self.get_or_create_collection(collection)
        coll.add(
            ids=list(ids),
            documents=list(chunks),
            embeddings=[list(e) for e in embeddings],
            metadatas=list(metadatas),
        )

    def delete_doc(self, collection: str, doc_name: str) -> int:
        """Delete every chunk where metadata.doc_name == doc_name.

        Returns the number of chunks removed (0 if collection or doc absent).
        """
        coll = self._get_collection_or_none(collection)
        if coll is None:
            return 0
        before = coll.count()
        coll.delete(where={"doc_name": doc_name})
        after = coll.count()
        return max(before - after, 0)

    # --- reads ---

    def query(
        self,
        collection: str,
        embedding: Sequence[float],
        k: int,
        where: dict | None = None,
    ) -> list[RetrievedChunk]:
        coll = self._get_collection_or_none(collection)
        if coll is None:
            return []
        if coll.count() == 0:
            return []

        result = coll.query(
            query_embeddings=[list(embedding)],
            n_results=k,
            where=where,
        )

        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]

        out: list[RetrievedChunk] = []
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
            score = float(1.0 - dist) if dist is not None else 0.0
            out.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    doc_name=str(meta.get("doc_name", "")),
                    chunk_index=int(meta.get("chunk_index", 0)),
                    text=str(doc),
                    score=score,
                    metadata=dict(meta),
                )
            )
        return out

    # --- helpers ---

    def _get_collection_or_none(self, name: str):
        try:
            return self._client.get_collection(name)
        except Exception:
            return None

    @staticmethod
    def _distinct_doc_count(coll) -> int:
        result = coll.get(include=["metadatas"])
        metas = result.get("metadatas") or []
        return len({meta.get("doc_name", "") for meta in metas})
