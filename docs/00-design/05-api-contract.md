# API contract

All endpoints are JSON over HTTP. The base URL in development is
`http://localhost:8000`. The full OpenAPI schema is also served at
`/docs` (Swagger UI) once the service is running.

## Conventions

- Request and response bodies are `application/json` unless otherwise
  noted (file upload uses `multipart/form-data`).
- All timestamps are ISO 8601 in UTC.
- Errors follow this shape:

  ```json
  {
    "error": "CollectionNotFound",
    "message": "Collection 'foo' does not exist.",
    "details": {}
  }
  ```

- HTTP status codes used: `200`, `201`, `204`, `400`, `404`, `422`,
  `502`, `500`.

## Endpoints

### `POST /ingest`

Upload one document into a collection. The collection is created if it
does not exist.

**Request** (`multipart/form-data`):

| field | type | required | description |
| --- | --- | --- | --- |
| `file` | file | yes | PDF, Markdown, or text file |
| `collection` | string | yes | target collection name |
| `tags` | string | no | comma-separated tags |

Example:

```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@data/raw/kubernetes/scaling.md" \
  -F "collection=kubernetes-docs" \
  -F "tags=scaling,hpa"
```

**Response** `201 Created`:

```json
{
  "doc_id": "0a3f6c2e-...-...",
  "doc_name": "scaling.md",
  "collection": "kubernetes-docs",
  "chunks_written": 14,
  "uploaded_at": "2026-05-03T16:42:11.832Z"
}
```

**Errors**:

- `422 IngestionError` — file could not be parsed
- `400` — missing `file` or `collection`

### `GET /collections`

List all collections and their document counts.

**Response** `200`:

```json
{
  "collections": [
    {"name": "kubernetes-docs", "doc_count": 3, "chunk_count": 42},
    {"name": "aws-docs",        "doc_count": 1, "chunk_count": 88}
  ]
}
```

### `GET /collections/{name}/docs`

List documents inside a collection.

**Response** `200`:

```json
{
  "collection": "kubernetes-docs",
  "docs": [
    {"doc_name": "scaling.md", "chunks": 14, "uploaded_at": "..."},
    {"doc_name": "hpa.md",     "chunks": 9,  "uploaded_at": "..."}
  ]
}
```

**Errors**: `404 CollectionNotFound`.

### `DELETE /collections/{name}/docs/{doc_name}`

Delete a single document (and all its chunks) from a collection.

**Response** `204 No Content`.

**Errors**: `404 CollectionNotFound`, `404 DocumentNotFound`.

### `DELETE /collections/{name}`

Delete an entire collection.

**Response** `204 No Content`.

**Errors**: `404 CollectionNotFound`.

### `POST /query`

Ask a question, scoped to a collection and optionally a subset of
documents.

**Request**:

```json
{
  "question": "How does the Horizontal Pod Autoscaler work?",
  "collection": "kubernetes-docs",
  "doc_filter": {
    "doc_name": ["hpa.md", "scaling.md"]
  },
  "strategy": "basic",
  "k": 5
}
```

| field | type | required | description |
| --- | --- | --- | --- |
| `question` | string | yes | user question |
| `collection` | string | yes | collection to query |
| `doc_filter` | object | no | restricts retrieval; supports `doc_name: string[]` and `tags: string[]` |
| `strategy` | enum | no | `"basic"` or `"improved"` (default: `"basic"`) |
| `k` | int | no | top-K (default from settings, typically 5) |

**Response** `200`:

```json
{
  "answer": "The Horizontal Pod Autoscaler scales the number of pod replicas...",
  "collection": "kubernetes-docs",
  "strategy": "basic",
  "sources": [
    {
      "chunk_id": "a1b2c3...",
      "doc_name": "hpa.md",
      "chunk_index": 2,
      "score": 0.87,
      "text": "The Horizontal Pod Autoscaler automatically scales..."
    }
  ],
  "latency_ms": 1240,
  "tokens": {"prompt": 812, "completion": 144}
}
```

**Empty-context response** `200` (no LLM call was made):

```json
{
  "answer": "I cannot answer this question from the provided documents.",
  "collection": "kubernetes-docs",
  "strategy": "basic",
  "sources": [],
  "latency_ms": 90,
  "tokens": null
}
```

**Errors**:

- `404 CollectionNotFound`
- `502 LLMUnavailable`
- `400` — missing `question` or `collection`

### `POST /compare`

Run both retrieval strategies on the same question and return both
results.

**Request**: same body as `/query`, but `strategy` is ignored.

**Response** `200`:

```json
{
  "question": "...",
  "collection": "kubernetes-docs",
  "basic":    { "answer": "...", "sources": [...], "latency_ms": 900,  "tokens": {...} },
  "improved": { "answer": "...", "sources": [...], "latency_ms": 1100, "tokens": {...} }
}
```

### `POST /evaluate`

Score one or more questions using RAGAS metrics.

**Request**:

```json
{
  "collection": "kubernetes-docs",
  "strategy": "basic",
  "items": [
    {
      "question": "What does HPA scale?",
      "ground_truth": "It scales the number of pod replicas..."
    }
  ]
}
```

`ground_truth` is optional per item; some metrics (faithfulness,
answer relevancy) work without it.

**Response** `200`:

```json
{
  "collection": "kubernetes-docs",
  "strategy": "basic",
  "results": [
    {
      "question": "What does HPA scale?",
      "answer": "...",
      "metrics": {
        "faithfulness": 0.92,
        "answer_relevancy": 0.88,
        "context_precision": 0.80
      }
    }
  ],
  "summary": {
    "faithfulness_avg": 0.92,
    "answer_relevancy_avg": 0.88,
    "context_precision_avg": 0.80
  }
}
```

### `GET /health`

Liveness check.

**Response** `200`:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "collections": 2
}
```

### `GET /logs?limit=N`

Tail of the structured query log. `limit` defaults to 50 and is capped
at 500.

**Response** `200`:

```json
{
  "limit": 50,
  "entries": [
    { "ts": "...", "endpoint": "/query", "question": "...", "...": "..." }
  ]
}
```

## Error catalog

| Code | HTTP | When raised |
| --- | --- | --- |
| `CollectionNotFound` | 404 | `collection` param does not exist |
| `DocumentNotFound` | 404 | `doc_name` not in collection |
| `IngestionError` | 422 | parsing/chunking failed |
| `LLMUnavailable` | 502 | Groq returned 5xx or timed out |
| `ValidationError` | 400 | Pydantic validation failed on request |

## Versioning

The API is versioned implicitly as `v0` for the duration of the
project. Breaking changes during the build phases are allowed; once
Phase 5 ships, any further breaking change must bump the path
prefix to `/v1/...`.
