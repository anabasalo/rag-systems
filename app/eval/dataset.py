"""Eval dataset loading.

Datasets are JSONL files with one question per line:

    {"question": "...", "ground_truth": "..."}

``ground_truth`` is optional. Files live under ``data/eval/`` by
convention. Filenames are referenced *without* the ``.jsonl``
extension when looked up by name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalItem:
    question: str
    ground_truth: str | None = None


class EvalDatasetError(ValueError):
    """Raised when an eval dataset cannot be loaded."""


def load_dataset(path: str | Path) -> list[EvalItem]:
    """Read a JSONL eval file. Skips blank lines."""
    p = Path(path)
    if not p.exists():
        raise EvalDatasetError(f"Eval dataset not found: {p}")

    items: list[EvalItem] = []
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvalDatasetError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
        question = obj.get("question")
        if not question or not isinstance(question, str):
            raise EvalDatasetError(f"{p}:{lineno}: missing or non-string 'question'")
        ground_truth = obj.get("ground_truth")
        if ground_truth is not None and not isinstance(ground_truth, str):
            raise EvalDatasetError(f"{p}:{lineno}: 'ground_truth' must be a string")
        items.append(EvalItem(question=question, ground_truth=ground_truth))

    if not items:
        raise EvalDatasetError(f"Eval dataset is empty: {p}")
    return items


def resolve_dataset_path(name: str, eval_dir: str | Path) -> Path:
    """Resolve ``name`` to a JSONL path under ``eval_dir``."""
    base = Path(eval_dir)
    candidate = base / f"{name}.jsonl"
    return candidate
