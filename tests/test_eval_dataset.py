"""Phase 4 eval-dataset loader tests."""

from __future__ import annotations

import pytest

from app.eval.dataset import EvalDatasetError, load_dataset


def _write(tmp_path, content: str):
    p = tmp_path / "x.jsonl"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_dataset_parses_lines(tmp_path):
    p = _write(
        tmp_path,
        '{"question":"Q1","ground_truth":"A1"}\n{"question":"Q2"}\n',
    )
    items = load_dataset(p)
    assert len(items) == 2
    assert items[0].question == "Q1"
    assert items[0].ground_truth == "A1"
    assert items[1].question == "Q2"
    assert items[1].ground_truth is None


def test_load_dataset_skips_blank_lines(tmp_path):
    p = _write(
        tmp_path,
        '\n{"question":"Q1"}\n\n{"question":"Q2"}\n\n',
    )
    items = load_dataset(p)
    assert [it.question for it in items] == ["Q1", "Q2"]


def test_load_dataset_missing_file_raises(tmp_path):
    with pytest.raises(EvalDatasetError):
        load_dataset(tmp_path / "missing.jsonl")


def test_load_dataset_invalid_json_raises(tmp_path):
    p = _write(tmp_path, '{"question":"Q1"}\n{not json\n')
    with pytest.raises(EvalDatasetError) as exc:
        load_dataset(p)
    assert "invalid JSON" in str(exc.value)


def test_load_dataset_missing_question_raises(tmp_path):
    p = _write(tmp_path, '{"ground_truth":"A"}\n')
    with pytest.raises(EvalDatasetError):
        load_dataset(p)


def test_load_dataset_non_string_ground_truth_raises(tmp_path):
    p = _write(tmp_path, '{"question":"Q","ground_truth":42}\n')
    with pytest.raises(EvalDatasetError):
        load_dataset(p)


def test_load_dataset_empty_file_raises(tmp_path):
    p = _write(tmp_path, "\n\n")
    with pytest.raises(EvalDatasetError):
        load_dataset(p)


def test_committed_sample_dataset_loads():
    """The shipped dataset under data/eval/sample.jsonl must be valid."""
    items = load_dataset("data/eval/sample.jsonl")
    assert len(items) >= 5
    assert all(it.question for it in items)
