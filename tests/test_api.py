"""Phase 2 API tests using FastAPI's TestClient.

Tests run against a real ChromaDB (in tmp_path) but with a fake
embedder and a fake generator so they are fast, deterministic, and
offline.
"""

from __future__ import annotations

import io


def _md_upload(name: str, content: str):
    return ("file", (name, io.BytesIO(content.encode()), "text/markdown"))


# --- /ingest ---


def test_ingest_creates_doc_and_returns_201(client):
    response = client.post(
        "/ingest",
        files=[_md_upload("hello.md", "Hello world. " * 100)],
        data={"collection": "demo"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["doc_name"] == "hello.md"
    assert body["collection"] == "demo"
    assert body["chunks_written"] >= 1
    assert body["doc_id"]
    assert body["uploaded_at"]


def test_ingest_with_tags(client):
    response = client.post(
        "/ingest",
        files=[_md_upload("hello.md", "alpha. " * 100)],
        data={"collection": "demo", "tags": "scaling, hpa"},
    )
    assert response.status_code == 201


def test_ingest_unsupported_extension_returns_422(client):
    response = client.post(
        "/ingest",
        files=[("file", ("notes.docx", io.BytesIO(b"junk"), "application/octet-stream"))],
        data={"collection": "demo"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "IngestionError"


def test_ingest_missing_collection_returns_422(client):
    # FastAPI returns 422 when a required Form field is missing.
    response = client.post(
        "/ingest",
        files=[_md_upload("a.md", "x. " * 50)],
    )
    assert response.status_code == 422


# --- /collections ---


def test_list_collections_after_ingest(client):
    client.post("/ingest", files=[_md_upload("a.md", "alpha. " * 100)], data={"collection": "col1"})
    client.post("/ingest", files=[_md_upload("b.md", "beta. " * 100)], data={"collection": "col2"})

    response = client.get("/collections")
    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body["collections"]}
    assert names == {"col1", "col2"}


def test_list_docs_in_collection(client):
    client.post("/ingest", files=[_md_upload("a.md", "alpha. " * 100)], data={"collection": "col1"})
    client.post("/ingest", files=[_md_upload("b.md", "beta. " * 100)], data={"collection": "col1"})

    response = client.get("/collections/col1/docs")
    assert response.status_code == 200
    body = response.json()
    names = {d["doc_name"] for d in body["docs"]}
    assert names == {"a.md", "b.md"}


def test_list_docs_unknown_collection_returns_404(client):
    response = client.get("/collections/nope/docs")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "CollectionNotFound"
    assert body["details"]["collection"] == "nope"


def test_delete_doc_removes_only_target(client):
    client.post(
        "/ingest", files=[_md_upload("keep.md", "Keep. " * 100)], data={"collection": "col1"}
    )
    client.post(
        "/ingest", files=[_md_upload("drop.md", "Drop. " * 100)], data={"collection": "col1"}
    )

    response = client.delete("/collections/col1/docs/drop.md")
    assert response.status_code == 204

    docs = client.get("/collections/col1/docs").json()["docs"]
    assert {d["doc_name"] for d in docs} == {"keep.md"}


def test_delete_doc_unknown_returns_404(client):
    client.post("/ingest", files=[_md_upload("a.md", "a. " * 100)], data={"collection": "col1"})
    response = client.delete("/collections/col1/docs/nope.md")
    assert response.status_code == 404
    assert response.json()["error"] == "DocumentNotFound"


def test_delete_collection(client):
    client.post("/ingest", files=[_md_upload("a.md", "a. " * 100)], data={"collection": "col1"})
    response = client.delete("/collections/col1")
    assert response.status_code == 204

    names = {c["name"] for c in client.get("/collections").json()["collections"]}
    assert "col1" not in names


def test_delete_unknown_collection_returns_404(client):
    response = client.delete("/collections/never-existed")
    assert response.status_code == 404
    assert response.json()["error"] == "CollectionNotFound"


# --- /query ---


def test_query_returns_answer_and_sources(client):
    client.post(
        "/ingest",
        files=[_md_upload("k.md", "Kubernetes scales pods. " * 100)],
        data={"collection": "k8s"},
    )

    response = client.post(
        "/query", json={"question": "How does scaling work?", "collection": "k8s"}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["answer"] == "Mock answer."
    assert data["collection"] == "k8s"
    assert data["strategy"] == "basic"
    assert data["sources"]
    for source in data["sources"]:
        assert source["doc_name"] == "k.md"
        assert "score" in source
        assert "text" in source
    assert data["tokens"] == {"prompt": 100, "completion": 20}
    assert data["latency_ms"] >= 0


def test_query_unknown_collection_returns_404(client):
    response = client.post("/query", json={"question": "?", "collection": "missing"})
    assert response.status_code == 404
    assert response.json()["error"] == "CollectionNotFound"


def test_query_empty_question_returns_422(client):
    client.post("/ingest", files=[_md_upload("a.md", "a. " * 100)], data={"collection": "demo"})
    response = client.post("/query", json={"question": "", "collection": "demo"})
    assert response.status_code == 422  # Pydantic validation


def test_query_with_doc_filter_scopes_results(client):
    client.post(
        "/ingest", files=[_md_upload("a.md", "Apple. " * 100)], data={"collection": "shared"}
    )
    client.post(
        "/ingest",
        files=[_md_upload("b.md", "Banana. " * 100)],
        data={"collection": "shared"},
    )

    response = client.post(
        "/query",
        json={
            "question": "What fruit?",
            "collection": "shared",
            "doc_filter": {"doc_name": ["a.md"]},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sources"]
    for source in data["sources"]:
        assert source["doc_name"] == "a.md"


def test_query_with_tag_filter_scopes_results(client):
    client.post(
        "/ingest",
        files=[_md_upload("with_tag.md", "alpha. " * 100)],
        data={"collection": "tagged", "tags": "wanted"},
    )
    client.post(
        "/ingest",
        files=[_md_upload("no_tag.md", "alpha. " * 100)],
        data={"collection": "tagged"},
    )

    response = client.post(
        "/query",
        json={
            "question": "alpha",
            "collection": "tagged",
            "doc_filter": {"tags": ["wanted"]},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sources"]
    for source in data["sources"]:
        assert source["doc_name"] == "with_tag.md"


def test_query_below_floor_returns_safe_answer_without_calling_llm(client):
    """If similarity_floor is high enough, we short-circuit before the LLM."""
    from app.api.deps import get_settings_dep
    from app.config import Settings

    client.post(
        "/ingest",
        files=[_md_upload("k.md", "Kubernetes scales pods. " * 100)],
        data={"collection": "k8s"},
    )

    high_floor = Settings(similarity_floor=0.99)
    client.app_instance.dependency_overrides[get_settings_dep] = lambda: high_floor

    response = client.post("/query", json={"question": "anything", "collection": "k8s"})
    assert response.status_code == 200
    data = response.json()
    assert "cannot answer" in data["answer"].lower()
    assert data["sources"] == []
    assert data["tokens"] is None
    assert client.fake_generator.calls == 0


def test_query_includes_chunk_index_in_prompt(client):
    """The assembled prompt must contain bracketed chunk indices for citations."""
    client.post(
        "/ingest",
        files=[_md_upload("a.md", "Pods scale based on CPU. " * 100)],
        data={"collection": "demo"},
    )
    response = client.post("/query", json={"question": "How do pods scale?", "collection": "demo"})
    assert response.status_code == 200
    assert client.fake_generator.last_call is not None
    _system, user = client.fake_generator.last_call
    assert "[1]" in user
    assert "(source: a.md)" in user


# --- /query strategy=improved ---


def test_query_with_improved_strategy_returns_improved(client):
    client.post(
        "/ingest",
        files=[_md_upload("hpa.md", "Horizontal Pod Autoscaler scales pods. " * 50)],
        data={"collection": "k8s"},
    )
    client.post(
        "/ingest",
        files=[_md_upload("ca.md", "Cluster Autoscaler resizes node pools. " * 50)],
        data={"collection": "k8s"},
    )

    response = client.post(
        "/query",
        json={
            "question": "horizontal pod autoscaler",
            "collection": "k8s",
            "strategy": "improved",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["strategy"] == "improved"
    assert data["sources"]
    # BM25 should pull hpa.md to the top regardless of fake-embedder noise.
    assert any(s["doc_name"] == "hpa.md" for s in data["sources"])


def test_query_with_invalid_strategy_returns_422(client):
    response = client.post(
        "/query",
        json={
            "question": "anything",
            "collection": "demo",
            "strategy": "magic",
        },
    )
    assert response.status_code == 422


# --- /compare ---


def test_compare_runs_both_strategies(client):
    client.post(
        "/ingest",
        files=[_md_upload("hpa.md", "Horizontal Pod Autoscaler. " * 50)],
        data={"collection": "k8s"},
    )
    client.post(
        "/ingest",
        files=[_md_upload("vpa.md", "Vertical Pod Autoscaler. " * 50)],
        data={"collection": "k8s"},
    )

    response = client.post(
        "/compare",
        json={"question": "horizontal pod autoscaler", "collection": "k8s"},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["question"] == "horizontal pod autoscaler"
    assert data["collection"] == "k8s"

    assert data["basic"]["strategy"] == "basic"
    assert data["improved"]["strategy"] == "improved"
    assert data["basic"]["sources"]
    assert data["improved"]["sources"]
    assert data["basic"]["latency_ms"] >= 0
    assert data["improved"]["latency_ms"] >= 0
    # Both strategies call the (mocked) generator once each.
    assert client.fake_generator.calls == 2


def test_compare_unknown_collection_returns_404(client):
    response = client.post("/compare", json={"question": "anything", "collection": "missing"})
    assert response.status_code == 404
    assert response.json()["error"] == "CollectionNotFound"


def test_compare_rejects_strategy_field(client):
    """``strategy`` is meaningless for /compare and must be rejected."""
    client.post("/ingest", files=[_md_upload("a.md", "a. " * 50)], data={"collection": "demo"})
    response = client.post(
        "/compare",
        json={"question": "?", "collection": "demo", "strategy": "basic"},
    )
    assert response.status_code == 422


# --- /evaluate ---


def test_evaluate_returns_per_item_and_summary(client):
    client.post(
        "/ingest",
        files=[_md_upload("k.md", "Kubernetes scales pods. " * 100)],
        data={"collection": "k8s"},
    )

    response = client.post(
        "/evaluate",
        json={
            "collection": "k8s",
            "strategy": "basic",
            "items": [
                {"question": "How does scaling work?", "ground_truth": "Pods scale."},
                {"question": "What about pods?"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["collection"] == "k8s"
    assert data["strategy"] == "basic"
    assert data["item_count"] == 2
    assert data["answered_count"] == 2
    assert data["declined_count"] == 0

    assert len(data["results"]) == 2
    first = data["results"][0]
    assert first["question"] == "How does scaling work?"
    assert first["ground_truth"] == "Pods scale."
    assert first["answer"] == "Mock answer."
    assert first["retrieved_doc_names"]
    assert all(name == "k.md" for name in first["retrieved_doc_names"])
    assert first["metrics"]["faithfulness"] == 0.5
    assert first["metrics"]["context_precision"] == 0.5

    second = data["results"][1]
    assert second["ground_truth"] is None
    assert second["metrics"]["context_precision"] is None
    assert second["metrics"]["context_recall"] is None

    assert data["summary"]["faithfulness_avg"] == 0.5
    # Only one item had ground_truth, so the gt-required metric average is over 1 item.
    assert data["summary"]["context_precision_avg"] == 0.5


def test_evaluate_unknown_collection_returns_404(client):
    response = client.post(
        "/evaluate",
        json={
            "collection": "missing",
            "strategy": "basic",
            "items": [{"question": "?"}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"] == "CollectionNotFound"


def test_evaluate_empty_items_returns_422(client):
    client.post("/ingest", files=[_md_upload("a.md", "a. " * 50)], data={"collection": "demo"})
    response = client.post(
        "/evaluate",
        json={"collection": "demo", "strategy": "basic", "items": []},
    )
    assert response.status_code == 422


def test_evaluate_with_improved_strategy(client):
    client.post(
        "/ingest",
        files=[_md_upload("hpa.md", "Horizontal Pod Autoscaler. " * 50)],
        data={"collection": "k8s"},
    )
    response = client.post(
        "/evaluate",
        json={
            "collection": "k8s",
            "strategy": "improved",
            "items": [{"question": "horizontal pod autoscaler"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy"] == "improved"
    assert data["answered_count"] == 1


def test_evaluate_below_floor_marks_item_declined(client):
    """If similarity_floor blocks every chunk, the runner records the
    safe answer and the scorer still runs (but on empty contexts)."""
    from app.api.deps import get_settings_dep
    from app.config import Settings

    client.post(
        "/ingest",
        files=[_md_upload("k.md", "Kubernetes scales pods. " * 100)],
        data={"collection": "k8s"},
    )

    high_floor = Settings(similarity_floor=0.99)
    client.app_instance.dependency_overrides[get_settings_dep] = lambda: high_floor

    response = client.post(
        "/evaluate",
        json={
            "collection": "k8s",
            "strategy": "basic",
            "items": [{"question": "anything"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["declined_count"] == 1
    assert data["answered_count"] == 0
    assert data["results"][0]["answer"].startswith("I cannot answer")
    assert data["results"][0]["retrieved_doc_names"] == []
    # Generator was never called for declined items.
    assert client.fake_generator.calls == 0
