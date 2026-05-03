# ADR 0004 — Fixed-size chunking with overlap

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

Documents have to be split into chunks before embedding. The choice
of chunking strategy directly affects retrieval quality:

- chunks too small → fragmented context, the LLM sees irrelevant
  fragments
- chunks too large → retrieval is "soggy", we waste context window
  on irrelevant text within a chunk
- chunks without overlap → information that straddles a boundary
  becomes unreachable

We need a default that is good enough across PDF, Markdown, and text
without per-document tuning.

## Decision

Use **fixed-size chunking with overlap** as the default strategy:

- target chunk size: **512 tokens** (approximated as ~2,000 characters
  using a fast character-based proxy)
- overlap: **50 tokens** (~200 characters)
- splits prefer paragraph and sentence boundaries within ±10% of the
  target size; only fall back to a hard character split as a last
  resort

The implementation lives in `app/core/ingestion.py` as a single
function. The chunk size and overlap are configuration values
(`CHUNK_SIZE`, `CHUNK_OVERLAP`) so they can be changed without code
changes — and exercises in the course encourage the reader to do so.

## Consequences

**Positive**:

- Predictable, easy to reason about. Two parameters, both
  configurable.
- Cheap and deterministic. No LLM calls during ingestion.
- Works adequately on all three input formats (PDF, MD, TXT).

**Negative / accepted trade-offs**:

- Fixed chunks ignore document semantics. A long code block or table
  may be split awkwardly.
- The character-to-token proxy is imprecise (chunk sizes vary by
  ±15%). For our use case this is fine; we are not pushing context
  window limits.
- When boundaries land in the middle of a sentence, retrieval can
  still surface the chunk via overlap, but the result reads less
  cleanly. The 50-token overlap is the primary mitigation.

## Alternatives considered

### Recursive character splitting (LangChain default)

- *Pros:* respects nested separators (`\n\n`, `\n`, `. `, ` `).
- *Cons:* basically a richer version of what we do; we get most of
  its benefit by preferring paragraph and sentence boundaries.
- *Verdict:* near-equivalent in quality for our corpus. We keep our
  implementation simpler.

### Semantic chunking (embedding-based)

- *Pros:* preserves topical coherence by splitting where adjacent
  sentences become semantically distant.
- *Cons:* expensive at ingest time (one embedding per sentence) and
  introduces a non-trivial threshold to tune. Hard to debug.
- *Verdict:* mentioned as an exercise; not the default.

### Token-aware chunking (tiktoken / model tokenizer)

- *Pros:* exact token counts.
- *Cons:* ties chunking to a specific tokenizer. Adds a dependency
  for a small benefit at our scale. The character-proxy stays well
  within the embedder's 256-token limit.

### Per-format custom splitters (Markdown headers, PDF page-aware)

- *Pros:* better quality on structured docs.
- *Cons:* three implementations to maintain. Out of scope for the
  initial build; could be a Phase 6 enhancement.

## When we would revisit

- evaluation shows context_precision is consistently below ~0.7
- we add a corpus that has a very different shape (e.g., transcripts,
  source code, chat logs)
- we hit context window limits at top-K
