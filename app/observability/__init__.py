"""Observability primitives.

Currently a single ``QueryLogger`` that writes a structured JSONL line
per request. Phase 5 wires it into ``/query``, ``/compare`` and
``/evaluate``; ``/logs`` and ``/health`` read from it.
"""
