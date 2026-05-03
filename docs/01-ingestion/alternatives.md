# Phase 1 — Alternatives

For each design decision in this phase, the alternatives we considered
and why we did not pick them. The full ADRs cross-referenced below
have more detail.

## Vector store

| Option | Pros | Cons |
| --- | --- | --- |
| **ChromaDB (chosen)** | embedded, persistent, native metadata filters, good Python ergonomics | embedded mode is single-process |
| FAISS | fast, mature | index-only — no metadata store, would need SQLite alongside |
| Pinecone | managed, scales effortlessly | paid, network dependency, conflicts with the zero-cost goal |
| Weaviate | hybrid retrieval and GraphQL out of the box | extra service to operate |
| pgvector (Postgres) | familiar database, transactional | requires running Postgres for what is at our scale a single index |
| Qdrant | fast, good filtering | very close to Chroma in capability but adds a separate container |

Decision recorded in [ADR 0001](../00-design/adrs/0001-vector-db-chromadb.md).

When we would revisit: corpus past ~100k chunks, multiple writer
processes, or cross-collection search as a first-class feature.

## Embedding model

| Option | Pros | Cons |
| --- | --- | --- |
| **`all-MiniLM-L6-v2` (chosen)** | tiny (~80 MB), CPU-friendly, 384 dims, solid baseline | quality below larger models, English-only, 256-token input cap |
| `bge-small-en-v1.5` | better MTEB scores, still small | slightly heavier; reasonable swap |
| `bge-large-en-v1.5` | strong quality | ~1.3 GB and noticeably slower on CPU |
| OpenAI `text-embedding-3-small` | very strong, predictable latency | paid (per token) |
| Cohere | good quality, free tier exists | account + network dependency |
| Instructor / E5 (instruction-tuned) | can boost retrieval | more setup (instruction prefixes), small win at our scale |

Decision recorded in [ADR 0003](../00-design/adrs/0003-embedding-model.md).

When we would revisit: corpus expands meaningfully, retrieval quality
plateaus, or we need multilingual support.

## Chunking strategy

| Strategy | Pros | Cons |
| --- | --- | --- |
| **Fixed-size + overlap with boundary preference (chosen)** | predictable, two parameters, fast, deterministic | ignores document semantics; long code blocks can be split awkwardly |
| Recursive character splitting (LangChain default) | respects nested separators | basically a richer version of what we do; we get most of the benefit |
| Semantic chunking (embedding-based) | preserves topical coherence | expensive at ingest time, threshold to tune, hard to debug |
| Token-aware (tokenizer-based) | exact token counts | ties chunking to a specific tokenizer; small gain at our scale |
| Per-format custom (Markdown headers, PDF page-aware) | better quality on structured docs | three implementations to maintain |

Decision recorded in [ADR 0004](../00-design/adrs/0004-chunking-strategy.md).

When we would revisit: evaluation shows context_precision is
consistently below ~0.7, or we add a corpus with very different shape
(transcripts, source code, chat logs).

## Scoping model

| Option | Pros | Cons |
| --- | --- | --- |
| **Collections + metadata filters (chosen)** | matches user mental model; clean isolation; native to Chroma | user must know which collection their docs are in |
| Single index with everything | simplest possible | no isolation, no efficient scoping |
| One collection per document | perfect isolation | explodes collection count, defeats the indexing point |
| Vendor-specific namespaces | clean in vendors that support them | not first-class in Chroma |
| Tag-only scoping | minimal | loses the "logical knowledge base" abstraction |

Decision recorded in [ADR 0005](../00-design/adrs/0005-scoping-collections-vs-namespaces.md).

When we would revisit: real multi-tenancy that must survive a
misconfigured tag, or a need for global cross-collection search.

## Configuration

We use **Pydantic Settings** with `.env` support.

| Option | Pros | Cons |
| --- | --- | --- |
| **Pydantic Settings (chosen)** | typed, validated, IDE-friendly, plays well with the rest of the stack | one more dep |
| `os.environ` directly | zero deps | untyped, easy to typo, validation by hand |
| `dynaconf` / `hydra` | rich features (multiple sources, layered) | overkill at our scope |
| `python-decouple` | simple | no validation |

## PDF parsing

We use **`pdfplumber`** as the default PDF parser.

| Option | Pros | Cons |
| --- | --- | --- |
| **`pdfplumber` (chosen)** | preserves layout reasonably, good text extraction, pure Python | slower than mining libraries on huge PDFs |
| `PyPDF2` / `pypdf` | mature, lightweight | poorer extraction on multi-column layouts |
| `pdfminer.six` | very accurate text extraction | API is fiddly; pdfplumber wraps it |
| Tika / Apache | best quality on weird PDFs | requires JVM; out of scope |
| `unstructured` | format-aware (HTML, DOCX, PDF, images) | heavy install, opinionated |

For our engineering-doc corpus, `pdfplumber` is the right balance.
