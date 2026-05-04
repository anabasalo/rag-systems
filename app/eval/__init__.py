"""Evaluation module.

Layered as ``api/evaluate.py -> eval/runner.py -> eval/scorer.py + eval/dataset.py``.
The Scorer Protocol means the API layer never imports RAGAS directly,
which keeps tests fast (a fake scorer is injected) and lets the
implementation evolve without touching handlers.
"""
