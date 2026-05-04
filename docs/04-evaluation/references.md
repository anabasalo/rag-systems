# Phase 4 — References

Curated reading for evaluation of RAG systems and LLM-as-judge methods.

## Foundational papers

- **Es et al., 2023 — *RAGAS: Automated Evaluation of
  Retrieval-Augmented Generation*.**
  https://arxiv.org/abs/2309.15217
  The paper that introduced the metrics this phase uses. Section 3
  defines faithfulness and answer relevancy in the form RAGAS
  implements; Section 4 covers the experimental validation against
  human judges. Read sections 2 and 3 first; the full paper is
  short.

- **Liu et al., 2023 — *G-Eval: NLG Evaluation using GPT-4 with
  Better Human Alignment*.**
  https://arxiv.org/abs/2303.16634
  The general-purpose LLM-as-judge methodology that RAGAS
  specializes for RAG. Worth reading for the meta-question:
  *under what conditions can an LLM grade an LLM?*

- **Zheng et al., 2023 — *Judging LLM-as-a-Judge with MT-Bench and
  Chatbot Arena*.**
  https://arxiv.org/abs/2306.05685
  The empirical study of LLM-judge biases (positional, verbosity,
  self-preference). Important context for *why* our Llama-judge
  scores are noisier than RAGAS' published GPT-4 numbers.

- **Saad-Falcon et al., 2023 — *ARES: An Automated Evaluation
  Framework for Retrieval-Augmented Generation Systems*.**
  https://arxiv.org/abs/2311.09476
  A contemporary alternative to RAGAS that uses fine-tuned
  classifiers instead of LLM judges. Good "compared to RAGAS"
  reading.

- **Bajaj et al., 2016 — *MS MARCO: A Human-Generated MAchine
  Reading COmprehension Dataset*.**
  https://arxiv.org/abs/1611.09268
  Pre-LLM RAG evaluation: human-written QA pairs over web passages.
  Reading the dataset description shows what "ground truth" looks
  like before LLM judges, and is a useful sanity check that our
  little 8-item JSONL is shaped sensibly.

- **Kandpal et al., 2023 — *Large Language Models Struggle to Learn
  Long-Tail Knowledge*.**
  https://arxiv.org/abs/2211.08411
  Empirical motivation for *why* RAG matters: parametric memory is
  unreliable on rare facts. The argument behind every faithfulness
  metric.

## Practical guides

- **RAGAS docs — *Concepts*.**
  https://docs.ragas.io/en/stable/concepts/index.html
  The library's own metric reference. Compare against our
  `concepts.md` — RAGAS' definitions are slightly more formal.

- **RAGAS docs — *Customising LLMs and Embeddings*.**
  https://docs.ragas.io/en/stable/howtos/customizations/customize_models.html
  Exactly the wiring we did with `LangchainLLMWrapper(ChatGroq(...))`
  and `LangchainEmbeddingsWrapper(...)`.

- **LangChain — *Evaluation*.**
  https://python.langchain.com/docs/guides/productionization/evaluation/
  LangChain's own evaluation framework. Useful as a "what does the
  field look like outside RAGAS?" tour.

- **OpenAI Evals.**
  https://github.com/openai/evals
  Less RAG-specific, more "LLM eval framework". Good reading for
  how to structure a *suite* of evaluations rather than one-off
  metric runs.

- **Anthropic — *Evals* (cookbook).**
  https://github.com/anthropics/anthropic-cookbook/tree/main/misc/evaluation
  Concrete patterns for testing LLM behaviors with structured
  prompts. Adjacent to RAG eval but instructive on *how* the LLM
  judges in our setup are reasoning.

## Books and courses

- **Zaharia, Chen, Davis, Lin et al., 2024 — *The Shift from Models
  to Compound AI Systems* (Berkeley AI Research blog).**
  https://bair.berkeley.edu/blog/2024/02/18/compound-ai-systems/
  Frames RAG, agents, and tool-use as components of a "compound
  system" and argues evaluation has to be system-level, not
  model-level. The motivation behind metrics like RAGAS.

- **Ribeiro, Wu, Guestrin & Singh, 2020 — *Beyond Accuracy:
  Behavioral Testing of NLP Models with CheckList*.**
  https://arxiv.org/abs/2005.04118
  Pre-LLM but the methodology — testing for specific *capabilities*
  rather than aggregate metric scores — is exactly what good RAG
  eval looks like in practice. The exercise list at the end of
  Phase 4's README borrows this thinking.

## Library references

- **`ragas` source — `ragas/metrics`.**
  https://github.com/explodinggradients/ragas/tree/main/src/ragas/metrics
  Read the prompts. Each metric has a Python file with the
  decomposition prompt as a multi-line string. That is the *actual*
  thing being scored; the metric formula is just a count over the
  yes/no outcomes.

- **`langchain-groq`.**
  https://python.langchain.com/docs/integrations/chat/groq/
  The shim that lets `LangchainLLMWrapper` accept Groq. Worth
  reading just to confirm there is no magic — `ChatGroq` is a
  thin chat-completion wrapper around the Groq SDK.

- **`langchain_core.embeddings.Embeddings`.**
  https://python.langchain.com/api_reference/core/embeddings.html
  Two methods. Our `_LangchainEmbedderAdapter` implements both in
  five lines.

## Critiques and limits worth reading

- **Krishna et al., 2023 — *Longeval: Guidelines for Human
  Evaluation of Faithfulness in Long-form Summarization*.**
  https://arxiv.org/abs/2301.13298
  Empirical evidence that even *humans* struggle to score
  faithfulness consistently on long answers. A reality check on
  how much trust to put in any single eval run.

- **Wang et al., 2023 — *Large Language Models are not Fair
  Evaluators*.**
  https://arxiv.org/abs/2305.17926
  Documents systematic biases in LLM-as-judge: position bias,
  verbosity bias, self-preference. Mitigations in the paper are
  worth applying when you graduate from "comparing strategies on
  a small dataset" to "publishing a leaderboard".

## Project artifacts

- [`docs/00-design/03-architecture.md`](../00-design/03-architecture.md)
  — the layered design that lets the eval module sit alongside
  retrieval and generation without entangling them.
- [`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md)
  — the `/evaluate` endpoint shape.
- [`tests/test_eval_dataset.py`](../../tests/test_eval_dataset.py),
  [`tests/test_eval_runner.py`](../../tests/test_eval_runner.py),
  [`tests/test_api.py`](../../tests/test_api.py) — every behavior
  the eval module claims to support has a named test. The
  `_FakeScorer` in `tests/conftest.py` is the pattern that lets
  tests exercise the runner without any real LLM call.
