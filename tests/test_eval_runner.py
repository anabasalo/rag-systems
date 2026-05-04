"""Phase 4 eval-runner tests.

These exercise ``run_evaluation`` against a real (in-tmp) ChromaDB,
the deterministic fake embedder, and the ``_FakeGenerator`` /
``_FakeScorer`` from ``conftest.py``. They never call Groq or RAGAS.
"""

from __future__ import annotations

from app.config import Settings
from app.core.ingestion import ingest
from app.db.vector_store import VectorStore
from app.eval.dataset import EvalItem
from app.eval.runner import NO_ANSWER, run_evaluation


def _populated_store(tmp_chroma_dir, fake_embedder, make_doc):
    store = VectorStore(persist_dir=tmp_chroma_dir)
    ingest(
        file_path=make_doc("k.md", "Kubernetes scales pods automatically. " * 30),
        collection="k8s",
        tags=[],
        embedder=fake_embedder,
        vector_store=store,
        chunk_size=2000,
        chunk_overlap=200,
    )
    return store


def test_run_evaluation_returns_per_item_and_summary(
    tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, make_doc
):
    store = _populated_store(tmp_chroma_dir, fake_embedder, make_doc)
    settings = Settings(similarity_floor=-1.0)

    result = run_evaluation(
        items=[
            EvalItem(question="How does scaling work?", ground_truth="Pods scale."),
            EvalItem(question="What about pods?"),
        ],
        collection="k8s",
        strategy="basic",
        settings=settings,
        vector_store=store,
        embedder=fake_embedder,
        generator=fake_generator,
        scorer=fake_scorer,
    )

    assert result.strategy == "basic"
    assert result.collection == "k8s"
    assert len(result.items) == 2
    assert result.answered_count == 2
    assert result.declined_count == 0

    item_with_gt = result.items[0]
    assert item_with_gt.metrics["faithfulness"] == 0.5
    assert item_with_gt.metrics["context_precision"] == 0.5

    item_without_gt = result.items[1]
    assert item_without_gt.metrics["faithfulness"] == 0.5
    # Metrics that need ground truth are None when it's missing.
    assert item_without_gt.metrics["context_precision"] is None
    assert item_without_gt.metrics["context_recall"] is None

    assert result.summary["faithfulness_avg"] == 0.5
    # Average over only the items that had values (1 of 2).
    assert result.summary["context_precision_avg"] == 0.5


def test_run_evaluation_short_circuits_on_floor_without_calling_generator(
    tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, make_doc
):
    store = _populated_store(tmp_chroma_dir, fake_embedder, make_doc)
    high_floor = Settings(similarity_floor=0.99)

    result = run_evaluation(
        items=[EvalItem(question="anything")],
        collection="k8s",
        strategy="basic",
        settings=high_floor,
        vector_store=store,
        embedder=fake_embedder,
        generator=fake_generator,
        scorer=fake_scorer,
    )

    assert fake_generator.calls == 0
    assert result.declined_count == 1
    assert result.answered_count == 0
    assert result.items[0].answer == NO_ANSWER
    assert result.items[0].retrieved_doc_names == []


def test_run_evaluation_passes_question_answer_contexts_to_scorer(
    tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, make_doc
):
    store = _populated_store(tmp_chroma_dir, fake_embedder, make_doc)
    settings = Settings(similarity_floor=-1.0)

    run_evaluation(
        items=[EvalItem(question="Q1", ground_truth="GT1")],
        collection="k8s",
        strategy="basic",
        settings=settings,
        vector_store=store,
        embedder=fake_embedder,
        generator=fake_generator,
        scorer=fake_scorer,
    )

    assert len(fake_scorer.calls) == 1
    sent = fake_scorer.calls[0]
    assert len(sent) == 1
    assert sent[0].question == "Q1"
    assert sent[0].ground_truth == "GT1"
    assert sent[0].answer == "Mock answer."
    assert sent[0].retrieved_contexts  # non-empty


def test_run_evaluation_with_improved_strategy(
    tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, make_doc
):
    store = _populated_store(tmp_chroma_dir, fake_embedder, make_doc)
    settings = Settings(similarity_floor=-1.0)

    result = run_evaluation(
        items=[EvalItem(question="scaling")],
        collection="k8s",
        strategy="improved",
        settings=settings,
        vector_store=store,
        embedder=fake_embedder,
        generator=fake_generator,
        scorer=fake_scorer,
    )
    assert result.strategy == "improved"
    assert result.answered_count == 1


def test_run_evaluation_summary_handles_all_none_metric(
    tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, make_doc
):
    """If every item lacks ground_truth, the gt-requiring metric averages
    are None, not crashes."""
    store = _populated_store(tmp_chroma_dir, fake_embedder, make_doc)
    settings = Settings(similarity_floor=-1.0)

    result = run_evaluation(
        items=[EvalItem(question="Q1"), EvalItem(question="Q2")],
        collection="k8s",
        strategy="basic",
        settings=settings,
        vector_store=store,
        embedder=fake_embedder,
        generator=fake_generator,
        scorer=fake_scorer,
    )
    assert result.summary["context_precision_avg"] is None
    assert result.summary["context_recall_avg"] is None
    assert result.summary["faithfulness_avg"] == 0.5
