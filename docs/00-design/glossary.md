# Glossary

A short reference for terms used throughout this project. Each entry
is one or two sentences and links to the doc where the concept is
explored more deeply.

---

**ADR (Architecture Decision Record).** A short document that captures
one significant architectural decision: its context, the decision,
the consequences, and the alternatives that were considered. ADRs in
this project live under `docs/00-design/adrs/`.

**Answer relevancy.** A RAGAS metric: how well the answer addresses
the question, regardless of whether it is grounded. Discussed in
Phase 4.

**BM25.** A classical sparse retrieval algorithm based on term
frequency and inverse document frequency. Strong baseline for keyword
matching; combined with dense retrieval to form *hybrid retrieval*.
Discussed in Phase 3.

**Chunk.** A small piece of a document (typically a few sentences to
a few paragraphs) that is independently embedded and stored in the
vector database. The unit of retrieval. See ADR 0004.

**Citation.** The chunks returned alongside an answer that show what
the answer is grounded in. Required by FR-3.2.

**Collection.** A named, isolated index in the vector database. The
project uses collections as logical knowledge bases (e.g.
`kubernetes-docs`). See ADR 0005.

**Context precision.** A RAGAS metric: of the chunks the system
retrieved, what fraction were actually useful for answering the
question. Discussed in Phase 4.

**Context window.** The maximum number of tokens an LLM can read in
one prompt (input + output). For Llama 3 8B on Groq this is 8,192.

**Cosine similarity.** The cosine of the angle between two vectors.
The default similarity measure for dense retrieval; high cosine
means semantically close.

**Dense retrieval.** Retrieval based on neural embeddings and a
similarity measure (cosine). Captures semantic similarity even when
the query and document share no words.

**Embedding.** A fixed-length numeric vector that represents a piece
of text in a way that captures its meaning. Produced by an embedding
model. See ADR 0003.

**Faithfulness.** A RAGAS metric: how much of the answer is actually
supported by the retrieved context. A high faithfulness score means
the answer did not hallucinate. Discussed in Phase 4.

**Generation.** The step where an LLM produces an answer from the
retrieved chunks plus the user question. The "G" in RAG.

**Grounding.** Constraining an LLM's answer to the content of
retrieved documents. Citations are the visible artifact of grounding.

**Hallucination.** When an LLM invents facts that are not supported
by its inputs. RAG reduces hallucination but does not eliminate it.

**Hybrid retrieval.** A retrieval strategy that combines a sparse
method (BM25) and a dense method (vector similarity), then fuses or
re-ranks the results. Implemented in Phase 3.

**Ingestion.** The pipeline that turns source documents into stored
chunks: parse → chunk → embed → write. Implemented in Phase 1.

**LLM (Large Language Model).** The model that generates the answer
text. This project uses Llama 3 via Groq by default. See ADR 0002.

**MMR (Maximal Marginal Relevance).** A re-ranking algorithm that
balances relevance to the query against diversity across results.
Used in the `improved` retrieval strategy to avoid returning K
near-duplicate chunks.

**Overlap.** The number of tokens that adjacent chunks share, so a
fact that lives near a chunk boundary is reachable via either chunk.
See ADR 0004.

**RAG (Retrieval-Augmented Generation).** A technique where, instead
of relying on an LLM's parametric memory, you retrieve relevant
documents at query time and put them in the prompt. The whole
project is one example.

**RAGAS.** An open-source library for evaluating RAG systems. Provides
LLM-as-judge implementations of metrics like faithfulness, answer
relevancy, and context precision.

**Re-ranking.** A second pass over an initial retrieval result that
re-orders chunks (or filters them) to improve quality. MMR is one
form; cross-encoder re-rankers are another.

**Sparse retrieval.** Retrieval based on word-level statistics
(typically BM25). Excellent for exact-keyword matching, weak for
paraphrased queries.

**Strategy.** In this project, a named retrieval implementation:
`basic` (dense only) and `improved` (hybrid + MMR). Selected via
the `strategy` field in `/query` and `/compare`.

**Top-K.** The number of chunks the retriever returns for a query,
controlled by the `k` parameter. Typical values are 3–10.

**Vector store / vector database.** A database optimized for storing
embeddings and answering nearest-neighbor queries quickly. This
project uses ChromaDB. See ADR 0001.
