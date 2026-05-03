# ADR 0002 — Use Groq as the LLM provider

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

The generation step requires an LLM that can:

- be called from a free or generous-free-tier API
- return responses fast enough to keep `/query` under 3 seconds
- support a 8k+ token context window (so we can fit retrieved chunks)
- not require local GPU hardware

## Decision

Use **[Groq](https://console.groq.com/)** as the LLM provider, with
`llama-3.1-8b-instant` (or the equivalent currently available
open-weights model) as the default. The model name is configurable
via the `LLM_MODEL` environment variable, and Groq periodically
deprecates and replaces models — see
[Groq deprecations](https://console.groq.com/docs/deprecations) when
the default stops working.

The Groq client is wrapped behind a small `Generator` interface in
`app/core/generation.py`, so tests can inject a fake.

## Consequences

**Positive**:

- Groq's free tier is generous enough for development and demos.
- Latency is exceptional (often under 500 ms for short prompts) which
  makes `/query` feel snappy.
- Open-weights models (Llama 3, Mixtral, etc.) avoid lock-in. The
  same prompts will work on Ollama or another provider.
- An OpenAI-compatible API surface (`groq` SDK) is straightforward
  to use.

**Negative / accepted trade-offs**:

- A network dependency: tests that hit Groq for real are gated behind
  a `network` pytest marker and skipped in CI.
- Free-tier rate limits exist. They are well above what a single
  developer needs but would not survive a real production load.
- The Groq SDK is a third-party dependency. If Groq disappears, we
  swap the implementation behind `Generator` for Ollama or another
  provider.

## Alternatives considered

### OpenAI

- *Pros:* gold-standard quality, large ecosystem.
- *Cons:* paid. Conflicts with NFR-4. The free trial credits are
  short-lived.

### Anthropic Claude

- *Pros:* high-quality answers, good at grounded responses.
- *Cons:* paid. Free tier is limited to a few prompts.

### Ollama (local models)

- *Pros:* fully local, fully free, no rate limits.
- *Cons:* requires a beefy CPU or GPU on the host. A typical laptop
  running `llama3:8b` will exceed our 3-second latency target. A
  good fallback if Groq is unavailable; we keep the `Generator`
  interface so swapping is one file.

### Hugging Face Inference API

- *Pros:* free tier exists.
- *Cons:* cold-start latency is high and can spike to many seconds
  on the first call. Inconsistent with NFR-1.

### llama.cpp / vLLM self-hosted

- *Pros:* fully controlled.
- *Cons:* operational overhead is large; out of scope for a 2-week
  project that aims to keep `docker compose up` simple.

## When we would revisit

- Groq deprecates the chosen model and there is no straightforward
  replacement
- we want offline/airgapped operation (switch to Ollama)
- we need higher-quality reasoning than Llama 3 8B provides; revisit
  paid options or larger Groq models
