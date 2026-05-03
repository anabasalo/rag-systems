# Phase 2 — References

Curated reading for the ideas this phase introduced. Each entry has a
short note explaining *why* it is worth your time given what we built.

## Foundational papers

- **Lewis et al., 2020 — *Retrieval-Augmented Generation for
  Knowledge-Intensive NLP Tasks*.**
  https://arxiv.org/abs/2005.11401
  The paper that named the pattern. Worth reading the abstract +
  Section 2 (the architecture) to see the original framing as a
  *learned* retriever combined with a generator. We use a much
  simpler pipeline (frozen embedder, no joint training), but the
  taxonomy of the components is the same.

- **Karpukhin et al., 2020 — *Dense Passage Retrieval for
  Open-Domain QA* (DPR).**
  https://arxiv.org/abs/2004.04906
  Why dense vector retrieval beats BM25 alone for QA. Phase 3 will
  reintroduce BM25 *alongside* vector retrieval; this paper explains
  why dense was the winning baseline first.

- **Liu et al., 2023 — *Lost in the Middle: How Language Models Use
  Long Contexts*.**
  https://arxiv.org/abs/2307.03172
  The empirical paper behind the "don't just stuff everything in"
  argument in `alternatives.md`. Models attend best to the start
  and end of long contexts and worst to the middle. Directly
  motivates keeping top-K small and chunks focused.

- **Ram et al., 2023 — *In-Context Retrieval-Augmented Language
  Models*.**
  https://arxiv.org/abs/2302.00083
  Useful counterpoint: shows that RAG works well even without any
  fine-tuning, just by prompting a frozen model with retrieved
  passages. This is essentially what `app/core/generation.py` does.

## Practical guides

- **OpenAI — *Retrieval Augmented Generation*.**
  https://platform.openai.com/docs/guides/retrieval
  Vendor-neutral enough to read for the prompt-engineering advice.
  Their "system message + retrieved snippets + question" pattern is
  the same shape we use in `assemble_prompt`.

- **Anthropic — *Long context tips* / *Citations* prompt cookbook.**
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips
  Claude-specific but the citation patterns generalize. Notably:
  asking the model to *quote* the relevant text inline before
  answering reduces hallucination further. A future improvement
  for our prompt template.

- **Pinecone — *Learn: Retrieval Augmented Generation*.**
  https://www.pinecone.io/learn/retrieval-augmented-generation/
  Friendly walkthrough of the same pipeline we built, with Pinecone
  as the vector store. Useful as a sanity check that our shape is
  conventional.

- **LangChain docs — *RetrievalQA*.**
  https://python.langchain.com/docs/concepts/rag/
  LangChain abstracts a lot of what we built by hand. Reading the
  abstraction is useful to see what we *chose not* to depend on and
  why. The Phase 0 architecture decision was to keep the codebase
  framework-light so the ideas stay legible.

## API and library references

- **FastAPI — *Dependencies*.**
  https://fastapi.tiangolo.com/tutorial/dependencies/
  Background for `app/api/deps.py`. Read the section on
  `app.dependency_overrides` for the testing pattern we use in
  `tests/conftest.py`.

- **FastAPI — *Handling errors*.**
  https://fastapi.tiangolo.com/tutorial/handling-errors/
  Specifically the `add_exception_handler` part — that is exactly
  what `app/main.py` does to map core exceptions to HTTP status
  codes.

- **Pydantic v2 — *Models* and *Field*.**
  https://docs.pydantic.dev/latest/concepts/models/
  https://docs.pydantic.dev/latest/concepts/fields/
  We rely on Pydantic for the API contract: `min_length`, regex
  `pattern`, default values, and the JSON-schema generation that
  drives `/docs`.

- **ChromaDB — *Collections* and *Where filters*.**
  https://docs.trychroma.com/usage-guide
  In particular the metadata `where` syntax we use to enforce
  `doc_filter.doc_name` and `doc_filter.doc_id` at the index level.

- **Groq — *API Reference* and *Models*.**
  https://console.groq.com/docs/api-reference
  https://console.groq.com/docs/models
  Latest model names and rate limits. Important because Groq
  deprecates models faster than typical providers — we already
  handled one deprecation during this build.

## Books and courses

- **Jurafsky & Martin — *Speech and Language Processing*, 3rd
  edition (draft).**
  https://web.stanford.edu/~jurafsky/slp3/
  Chapters 6 (vector semantics), 14 (QA), and 15 (chatbots) provide
  the textbook background to retrieval and prompting. Free.

- **Andrew Ng — *Building Systems with the ChatGPT API* (DeepLearning.AI,
  short course).**
  https://www.deeplearning.ai/short-courses/building-systems-with-chatgpt/
  Goes through the same pattern (retrieve, assemble, generate) at a
  beginner level. Useful as a 1-hour reinforcement.

## Adjacent reading worth a skim

- **Gao et al., 2023 — *Retrieval-Augmented Generation for Large
  Language Models: A Survey*.**
  https://arxiv.org/abs/2312.10997
  A survey of every RAG variation that has been published. Use it
  as a map when Phase 3 (improved retrieval), Phase 4 (evaluation),
  or future "agentic" extensions need to be researched.

- **Shi et al., 2023 — *Large Language Models Can Be Easily
  Distracted by Irrelevant Context*.**
  https://arxiv.org/abs/2302.00093
  Direct evidence for why the similarity floor matters. Including
  irrelevant chunks does not just waste tokens, it actively
  *degrades* answer quality.

- **Asai et al., 2023 — *Self-RAG: Learning to Retrieve, Generate,
  and Critique Through Self-Reflection*.**
  https://arxiv.org/abs/2310.11511
  Where this pattern is going next: models that decide *when* to
  retrieve and *what* to keep. Out of scope for this project but
  the natural follow-up after Phase 4's evaluation.

## Project artifacts that are useful references in their own right

- [`docs/00-design/03-architecture.md`](../00-design/03-architecture.md)
  — the layered design enforced by Phase 2's code.
- [`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md)
  — the source of truth for endpoint shapes; revisit before Phase 3
  adds `/compare`.
- [`docs/00-design/adrs/0002-llm-provider-groq.md`](../00-design/adrs/0002-llm-provider-groq.md)
  — the LLM-provider decision, with the Groq-model-deprecation
  postscript.
- [`docs/00-design/adrs/0005-scoping-collections-vs-namespaces.md`](../00-design/adrs/0005-scoping-collections-vs-namespaces.md)
  — why `collection` + `doc_filter` is a two-layer scoping model.
- [`tests/test_api.py`](../../tests/test_api.py) — every behavior
  this phase claims to support is pinned by a named test. Reading
  the test names is an executable summary of the contract.
