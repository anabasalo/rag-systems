"""LLM generation: prompt assembly and provider call.

The Groq SDK is wrapped behind a small ``Generator`` Protocol so tests
can inject a fake. See ADR 0002 for why Groq.

The prompt instructs the model to (a) answer only from context, and
(b) decline if the context does not contain the answer. This is what
gives us the "I don't know" property we will measure in Phase 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import LLMUnavailable
from app.db.vector_store import RetrievedChunk

SYSTEM_PROMPT = (
    "You are a precise technical assistant. Answer the user's question using "
    "ONLY the information in the provided context chunks. If the answer is not "
    "in the context, reply exactly: "
    '"I cannot answer this question from the provided documents." '
    "When you make a claim, cite the supporting chunk by its bracketed "
    "index (for example, [2]). Do not invent facts."
)


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    prompt_tokens: int | None
    completion_tokens: int | None


class Generator(Protocol):
    def generate(self, system: str, user: str) -> GenerationResult: ...


def assemble_prompt(question: str, chunks: Sequence[RetrievedChunk]) -> tuple[str, str]:
    """Return ``(system, user)`` messages for the chat completion call.

    Each chunk is presented with a 1-based bracketed index that the LLM is
    instructed to cite. The chunk's ``doc_name`` is included so the model
    can mention it where helpful.
    """
    if not chunks:
        # Defensive: callers should not invoke generation with no chunks; the
        # /query handler short-circuits instead. Keep behavior obvious here.
        context = "(no context retrieved)"
    else:
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            parts.append(f"[{i}] (source: {chunk.doc_name})\n{chunk.text}")
        context = "\n\n".join(parts)

    user_msg = (
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer (use only the context above; cite chunks like [n]):"
    )
    return SYSTEM_PROMPT, user_msg


class GroqGenerator:
    """Generator backed by the Groq SDK. Client is loaded lazily."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.0) -> None:
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:  # pragma: no cover - import-time guard
                raise LLMUnavailable("groq SDK is not installed") from exc
            if not self._api_key:
                raise LLMUnavailable("GROQ_API_KEY is not set")
            self._client = Groq(api_key=self._api_key)
        return self._client

    def generate(self, system: str, user: str) -> GenerationResult:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._temperature,
            )
        except Exception as exc:  # noqa: BLE001 - intentional: any vendor error
            raise LLMUnavailable(f"Groq call failed: {exc}") from exc

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return GenerationResult(
            answer=(choice.message.content or "").strip(),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
