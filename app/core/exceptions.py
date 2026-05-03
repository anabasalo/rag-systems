"""Custom exceptions raised by `app.core.*`.

Layers below `api/` MUST NOT raise FastAPI's `HTTPException` directly.
The API layer catches these in `app/main.py` and maps them to HTTP
status codes per the contract in `docs/00-design/05-api-contract.md`.
"""

from __future__ import annotations


class CollectionNotFound(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Collection '{name}' does not exist.")


class DocumentNotFound(Exception):
    def __init__(self, collection: str, doc_name: str) -> None:
        self.collection = collection
        self.doc_name = doc_name
        super().__init__(f"Document '{doc_name}' not found in collection '{collection}'.")


class LLMUnavailable(Exception):
    """Raised when the LLM provider returns an error or is misconfigured."""
