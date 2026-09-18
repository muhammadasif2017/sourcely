# Spec: Sourcely (proof of concept)

## Objective

Build a small backend that answers questions from documents a client has uploaded. It runs the full retrieval-augmented generation (RAG) flow:

```
Document -> Chunks -> Embeddings -> Vector store -> Semantic search -> Retrieved context -> LLM answer
```

The users are developers who evaluate or extend the service over HTTP. There is no frontend, no auth and no multi-tenancy.

### User stories

1. As a client, I send a text document and get back its id and chunk count, so I know it is searchable.
2. As a client, I send a query and get the most similar chunks with similarity scores and their source document.
3. As a client, I ask a question and get an answer grounded in the stored documents, with the sources that were used.
4. As an operator, I set providers, models, keys and tuning values in `.env` without touching code.
5. As a client, I list the stored documents and delete one I no longer want searchable.
6. As a client, I restrict search and ask to certain documents or metadata values.
7. As a client, I stream the answer token by token instead of waiting for the full response.
8. As an operator, I run the whole service with one `docker compose up`.

## Decisions (confirmed with the user)

| Concern | Decision | Why |
|---|---|---|
| Vector store | ChromaDB `PersistentClient`, cosine space, on disk at `CHROMA_PATH` | Embedded, so no server or Docker. Persists across restarts. |
| Embeddings | Local `fastembed`, `BAAI/bge-small-en-v1.5` (384 dimensions) | No key, no cost. Claude has no embeddings API. |
| Generation | `LLM_PROVIDER=openai` (default) or `anthropic` (`claude-opus-5`). The `openai` provider accepts `OPENAI_BASE_URL`, so it can also talk to any OpenAI-compatible server. | The client asked for "OpenAI or Claude", and both work by changing `.env` alone. The developer has no paid keys, so development runs free on Gemini. |
| Development LLM | Gemini `gemini-3.5-flash-lite` through Google's OpenAI-compatible endpoint, on the free tier | Verified live on 2026-09-18: 1.6s, 12 tokens for a trivial call. `gemini-2.5-*` now returns 404 for new users. The version is pinned rather than the `-latest` alias, so results stay reproducible. Ollama `qwen2.5:3b` is the offline fallback. |
| Claude refusals | `fallbacks="default"` with beta `server-side-fallback-2026-07-01` | Recommended default for `claude-opus-5`. A remaining refusal becomes a 502. |
| Chunking | Recursive character splitter: paragraph, then line, then sentence, then word, then a hard cut. Configurable size and overlap. | Keeps chunks on natural boundaries. No LangChain dependency. |
| Python | 3.12, pinned in `.python-version` | The system Python 3.14 lacks reliable ONNX runtime wheels. |

## Tech stack

Python 3.12, FastAPI 0.141, Uvicorn, Pydantic 2 plus pydantic-settings, chromadb 1.5, fastembed 0.8, anthropic 1.6, openai 3.15, python-multipart. Dev tools: pytest, httpx, ruff. Package manager: uv.

## API contract

All bodies are JSON unless stated otherwise. Errors use FastAPI's shape: `{"detail": ...}`.

### `POST /documents`: ingest one text document

Request:

```json
{ "text": "...", "document_id": "optional-id", "title": "optional", "metadata": {"source": "wiki"} }
```

- `text`: required. Must contain non-whitespace. At most `MAX_DOCUMENT_CHARS` characters (default 200,000). A longer text returns **413**.
- `document_id`: optional, `^[A-Za-z0-9._-]{1,128}$`. When absent, the server generates a UUID. When the id already exists, the server **replaces** that document's chunks, so re-ingesting a document is idempotent.
- `title`: optional, at most 200 characters. When absent, it is stored and returned as `""`, because Chroma metadata cannot hold `null`.
- `metadata`: optional flat map with at most 20 keys. Keys match `^[A-Za-z][A-Za-z0-9_]{0,63}$`. The server reserves `document_id`, `chunk_index` and `title`, and rejects them with 422. Values are str, int, float or bool, because Chroma stores only scalar values.

Response **201**:

```json
{ "document_id": "…", "title": "…", "chunks": 7, "characters": 5123 }
```

### `POST /documents/upload`: ingest a `.txt` or `.md` file (multipart)

The request has a `file` field and an optional `document_id` field. The server decodes the file as UTF-8, uses the filename as the default title, then follows the same rules as `POST /documents`. Any other file extension returns **415**. A file that is not valid UTF-8 returns **422**.

Details settled in Task 6: the extension check ignores case (`.MD` is accepted). A UTF-8 byte order mark is removed. The title is the file's base name, without any client-side path, cut to 200 characters. An empty or whitespace-only file returns 422. The server reads at most `4 × MAX_DOCUMENT_CHARS` bytes (the most a text within the character limit can take in UTF-8) and returns 413 beyond that, so an oversized file is never held in memory whole. Metadata can't be sent with an upload; use `POST /documents` for that.

### `GET /documents`: list documents

Returns **200** `{ "documents": [ { "document_id": "…", "title": "…", "chunks": 7, "metadata": {} } ] }`, sorted by `document_id`. The server builds the list by reading chunk metadata, so its cost grows with the number of chunks. That is acceptable for a PoC and noted as a scaling limit.

### `DELETE /documents/{document_id}`: delete a document

Removes every chunk of that document. Returns **204** when the document existed and **404** when it did not, with `{"detail": "Document '<id>' not found"}`. An id that breaks the `document_id` pattern returns **422**, because no stored document can have it.

### `POST /search`: semantic search

Request: `{ "query": "…", "top_k": 4, "filters": { "document_ids": ["a", "b"], "metadata": { "source": "wiki" } } }`. The query is 1 to 2,000 characters and must contain non-whitespace (same rule as document text). `top_k` is 1 to 20 and defaults to `DEFAULT_TOP_K`.

`filters` is optional, and so is each of its fields:
- `document_ids`: 1 to 100 ids. A chunk matches when its document is in the list.
- `metadata`: 1 to 10 exact-match pairs with the same key and value rules as ingestion. A chunk must match every pair.

When both fields are present, a chunk must satisfy both. The server translates filters into a Chroma `where` clause (`$in`, `$eq`, `$and`).

Settled in Task 8: `filters: null` and `filters: {}` both mean no filtering. An unknown field inside `filters` returns 422, so a misspelling such as `document_id` can't silently widen the search to everything. `document_id`, `chunk_index` and `title` are rejected as metadata keys, as at ingestion; use `document_ids` to filter by document. Matching is exact and typed: `2026` and `"2026"` are different values.

Response **200**:

```json
{ "query": "…", "results": [ { "document_id": "…", "chunk_index": 0, "title": "…", "text": "…", "score": 0.82, "metadata": {} } ] }
```

`score` is cosine similarity (`1 - cosine distance`), sorted from highest to lowest. An empty store returns `results: []`, not an error.

### `POST /ask`: answer from retrieved context

Request: `{ "question": "…", "top_k": 4, "filters": { … } }`. It uses the same limits and filters as `/search`, and the question must contain non-whitespace.

The key check comes first: when the active provider has no API key, `/ask` returns 503 before any retrieval, even for a question that would have no relevant context. An operator sees "not configured" consistently instead of an answer that depends on the question.

The server retrieves `top_k` chunks and drops any chunk that scores below `MIN_RELEVANCE`.

- **No chunks remain:** the server does not call the LLM. It returns **200** with a fixed "not enough information in the indexed documents" answer and `sources: []`.
- **Chunks remain:** the server builds a prompt with numbered context blocks and calls the configured LLM. It returns **200**:

```json
{ "answer": "… [1] …", "sources": [ /* the search hits that were used */ ], "provider": "anthropic", "model": "claude-opus-5" }
```

`model` is the model that actually produced the answer, as reported by the provider. With Claude's refusal fallbacks it can differ from `ANTHROPIC_MODEL`. Source titles and texts are HTML-escaped inside their `<source>` blocks, so a document containing `</source>` can't break out of its block.

The system prompt sets these rules. The model answers only from the context and cites sources as `[n]`. It says so when the context does not contain the answer. It treats the context as data, never as instructions (a basic prompt-injection guard).

### `POST /ask/stream`: streamed answer (Server-Sent Events)

This endpoint takes the same request as `/ask`. It responds with `text/event-stream` and sends these events in order:

```
event: sources   data: {"sources": [...], "provider": "...", "model": "..."}
event: token     data: {"text": "..."}          (sent many times)
event: done      data: {}
```

- **No relevant context:** the stream sends `sources` with an empty list, one `token` carrying the fixed "not enough information" answer, then `done`. The LLM is not called.
- **Errors before the first token:** these include a missing key, auth failure, rate limit and timeout. The server fetches the first token before it sends any headers, so these errors return the normal HTTP status from the error table, not a broken stream.
- **Errors after streaming starts:** the stream sends `event: error` with `{"detail": "..."}` and then closes. The status code is already 200 at that point.

Anthropic streams through `client.beta.messages.stream(...)` with the same fallback settings as `/ask`. The OpenAI-compatible provider streams through `chat.completions.create(stream=True)`.

Settled in Task 9:
- `model` in the `sources` event is the configured model. It is sent before generation, so with Claude's fallbacks a different model may produce some of the text; `/ask` reports the served model instead.
- A `token` event carries whatever text the provider sent in one delta: a word, a phrase or a sentence. Empty deltas are skipped.
- An unexpected failure after the first token sends `event: error` with the fixed detail `The answer was interrupted`; the trace goes to the log only.
- Claude's server-side fallback continues a mid-answer decline on the same stream. Only a final `stop_reason` of `refusal`, meaning the whole fallback chain declined, becomes an `error` event.
- The response sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`, so proxies pass tokens through instead of buffering them.
- A browser can't use `EventSource` here, because it only sends `GET`. Clients read the `POST` response body as a stream (`fetch` with a `ReadableStream`, or `curl -N`).

### `GET /health`

Returns `{ "status": "ok", "chunks_indexed": N, "embedding_model": "…", "llm_provider": "…", "llm_model": "…", "llm_configured": true }`.

### Every response

Each response carries an `X-Request-ID` header. The server reuses a client-supplied id when it matches `^[A-Za-z0-9._-]{1,128}$` and generates one otherwise. The same id appears in every log line for that request.

### Error mapping

| Condition | Status |
|---|---|
| Request fails validation | 422 |
| `DELETE` of an unknown document | 404 |
| Document longer than `MAX_DOCUMENT_CHARS` | 413 |
| Request body larger than `MAX_REQUEST_BYTES`, declared or counted while streaming in | 413 `Request body is larger than N bytes`, before the body is read |
| `Content-Length` header that isn't a number | 400 |
| Upload has the wrong file type | 415 |
| `/ask` called when the LLM API key is missing | 503 "LLM provider not configured" |
| LLM provider rejects the call (auth, bad request, refusal) | 502 |
| LLM provider rate-limits or is overloaded | 503 |
| LLM call times out or cannot connect | 504 |
| Unhandled exception | 500 with a generic message. The full trace goes to the log, never to the response. |

`/documents` and `/search` never need an LLM key.

## Configuration (`.env`)

| Variable | Default |
|---|---|
| `LLM_PROVIDER` | `openai` |
| `ANTHROPIC_API_KEY` | none |
| `ANTHROPIC_MODEL` | `claude-opus-5` |
| `OPENAI_API_KEY` | none |
| `OPENAI_MODEL` | `gpt-5-mini` (`.env.example` sets `gemini-3.5-flash-lite`) |
| `OPENAI_BASE_URL` | none, meaning api.openai.com. `.env.example` sets `https://generativelanguage.googleapis.com/v1beta/openai/`. |
| `LLM_MAX_TOKENS` | `16000` |
| `LLM_TIMEOUT_SECONDS` | `120` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_CACHE_DIR` | `./data/models`. This is where fastembed stores the downloaded model. |
| `EMBEDDING_QUERY_PREFIX` | `Represent this sentence for searching relevant passages: ` (bge's retrieval instruction). Added to queries only, never to documents. Set it to empty for a model without an instruction. |
| `CHROMA_PATH` | `./data/chroma` |
| `COLLECTION_NAME` | `documents` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` characters. Overlap must be smaller than size. |
| `MAX_DOCUMENT_CHARS` | `200000` |
| `MAX_REQUEST_BYTES` | `2097152` (2 MiB). The largest body the server reads. It admits a maximum-size document even with every character JSON-escaped (6 bytes each). |
| `DEFAULT_TOP_K` | `4` |
| `MIN_RELEVANCE` | `0.58`, calibrated at Checkpoint B (see Open questions) for bge-small with the query prefix. Recalibrate after changing the model or the prefix. |
| `LOG_LEVEL` | `INFO` |

Invalid configuration, such as overlap ≥ size or an unknown provider, fails at startup with a clear error.

`.env.example` makes Gemini's free tier the active setup. It includes commented blocks for real OpenAI, Claude and local Ollama. A missing key never stops the server from starting: `/ask` returns 503, and `/documents` and `/search` keep working.

**Free-tier data warning (repeated in the README):** Google may use prompts and responses sent on the free tier to improve its products. Do not ingest confidential text while using a free-tier key.

## Commands

```
Docker:   docker compose up --build
Install:  uv sync
Dev:      uv run uvicorn app.main:create_app --factory --reload
Test:     uv run pytest -q
Lint:     uv run ruff check . && uv run ruff format --check .
Types:    uv run mypy
Hooks:    uv run pre-commit install   (once), then hooks run on every commit
```

## Project structure

This is a layered layout, chosen by the user as standard practice. Routes stay thin, and the logic lives in services.

```
app/
  main.py               create_app() factory: lifespan, middleware, exception handlers, routers
  api/
    deps.py             Depends() getters for settings, embedder, store and LLM (read from app.state)
    middleware.py       RequestContextMiddleware: X-Request-ID and one access-log line per request
    routes/             One router per resource: health, documents, search, ask
  core/
    config.py           Settings (pydantic-settings, reads .env)
    errors.py           AppError and the exception handlers
    logging.py          Log format with the request id
  schemas/              Pydantic request and response models, one module per resource
  services/
    chunking.py         chunk_text(text, size, overlap)
    embeddings.py       Embedder protocol plus FastEmbedEmbedder
    vector_store.py     VectorStore over a Chroma collection, plus build_where
    llm.py              Prompt building, OpenAICompatibleLLM, AnthropicLLM, create_llm, LLMError
    rag.py              Retrieval and answer orchestration used by /ask and /ask/stream
tests/
  conftest.py           Fake embedder, fake LLM, isolated in-memory store, TestClient fixture
  unit/                 Pure logic: config, chunking, where-builder, LLM adapters with fake SDK clients
  integration/          HTTP-level tests through TestClient
.github/workflows/ci.yml  ruff, mypy and pytest on push and PR
.pre-commit-config.yaml   Hygiene hooks plus ruff and mypy
Dockerfile, docker-compose.yml, .dockerignore
docs/
  BUILD_LOG.md          Step-by-step build record with the concept behind each step (for learning)
  TECH_STACK.md         Why each technology was chosen: problem solved, advantages, alternatives, limits
  INTERVIEW_PREP.md     Likely interview questions with answers tied to this code
CLAUDE.md               Agent rules: commands, conventions, boundaries, verified gotchas
.env.example, README.md, SPEC.md, tasks/, pyproject.toml, uv.lock, .python-version
```

There is no module-level `app` object. The server runs through `uvicorn app.main:create_app --factory`, so importing the package never reads `.env` or loads models.

## Code style

This style follows the sibling projects: type hints everywhere, small modules, and dependencies injected through `app.state` so tests can swap them. Every public function and class has a docstring. Inline comments explain *why*, not *what*. Ruff runs with line length 100 and rules `E, F, I, UP, B`. mypy runs in `strict` mode with the pydantic plugin on `app/`. Routes declare `response_model` and status codes, so the OpenAPI docs at `/docs` are accurate.

```python
def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of at most `size` characters on natural boundaries.

    Consecutive chunks share up to `overlap` characters of trailing context.
    """
```

## Testing strategy

- **Filter translation** (`test_store.py`): filter objects become the expected Chroma `where` clauses, and filtered search returns only matching chunks.
- **Streaming** (`test_api.py`): event order, the no-context path, a pre-stream error returning the right HTTP status, and a mid-stream error producing an `error` event.
- **Docker:** `docker compose up --build` then `curl /health` returns 200. This runs manually once.
- **Unit tests** (`test_chunking.py`): short text gives one chunk. Every chunk stays within the size limit. Overlap is present. No words are lost. Invalid parameters are rejected.
- **API tests** (`test_api.py`): these use FastAPI `TestClient` with a deterministic fake embedder (a hashed bag of words), a fake LLM that records its prompt, and an in-memory Chroma collection with a unique name per test. They cover every endpoint, every row of the error table, re-ingest replacement, relevance ordering, the no-context path skipping the LLM, and the context actually reaching the prompt.
- **Live end-to-end check** (manual, run once before handoff): start the real server with the real fastembed model and Gemini `gemini-3.5-flash-lite` (free tier), then run ingest, search and ask with curl. This uses about 5 requests of the daily quota. The OpenAI path is the same code with a different base URL. The Anthropic path is covered by unit tests with a fake client and is written against the installed SDK's checked signatures. It cannot be verified live without an `ANTHROPIC_API_KEY`, and the README says so.
- Tests never call paid APIs and never download models.

## Boundaries

- **Always:** validate every input at the API edge, keep `.env` out of git, run `pytest` and `ruff` before calling a task done, and keep docstrings on every public function and class.
- **Ask first:** adding dependencies beyond the list above, switching the vector store, adding auth, and committing.
- **Never:** commit secrets, write real keys into `.env.example`, call paid APIs from tests, or return stack traces to clients.

## Success criteria

1. `uv run pytest -q` passes, and `ruff check` is clean.
2. With a fresh `data/` directory, a live run of `POST /documents`, then `POST /search`, then `POST /ask` returns the relevant chunk first and an answer that cites it. The data persists across a server restart.
3. `/ask` about something absent from the corpus returns the "not enough information" answer without an LLM call.
4. Every error row in the table can be triggered and returns the stated status.
5. A new developer can follow the README from clone to a working `/ask` call.
6. A live `/ask/stream` call on Gemini sends tokens as separate events, and `curl -N` shows the text arriving progressively.
7. After `DELETE`, the document is gone from `GET /documents` and from `/search` results.
8. `docker compose up --build` serves a healthy API, and the data survives a container restart.

### Evidence (final verification, 2026-09-19)

| # | Criterion | Evidence |
|---|---|---|
| 1 | Tests and lint | `uv run pytest -q`: 233 passed. `ruff check`, `ruff format --check` and `mypy` (strict): clean. The pre-commit hooks run the same checks on every commit, and CI runs them on push. |
| 2 | Live ingest, search, ask; persistence | Following the README against a fresh `CHROMA_PATH` with Gemini `gemini-3.5-flash-lite`: `POST /documents` returned 201; `/search` "how many vacation days do I get" ranked `leave-policy` first (0.65); `/ask` "Do part-time workers get holiday?" answered "Yes, part-time staff receive paid annual leave (holiday) pro-rated to their contracted hours [1]." citing `leave-policy` (0.71). Persistence: at Checkpoint B a restart with the same `CHROMA_PATH` kept both chunks and search still found the right document. |
| 3 | Absent topic, no LLM call | `/ask` "What is the capital of France?" returned the fixed answer with `sources: []`. `test_off_topic_question_skips_llm` and `test_empty_store_returns_fixed_answer_without_llm_call` assert the LLM is never called. |
| 4 | Every error row | Each row has a test: 422 (`test_invalid_input_returns_422` for every endpoint, invalid filters and uploads), 404 (`test_delete_unknown_returns_404`), 413 (`test_text_over_limit_returns_413`, `test_declared_length_over_limit_returns_413`, `test_chunked_body_over_limit_returns_413`), 415 (`test_other_file_types_return_415`), 400 (`test_invalid_content_length_returns_400`), 503 not configured (`test_missing_key_returns_503`), 502/503/504 (`test_llm_errors_map_to_their_status`, `test_error_before_first_token_keeps_http_status`, and the SDK mapping tests in `tests/unit/test_llm.py`), 500 (`test_unhandled_error_returns_generic_500`). Live: Gemini's bad-key 400 became a 502 in Task 5; a 2.2 MB upload got 413 in Docker. |
| 5 | README from clone to `/ask` | Every README curl example was run as written against a fresh index: health, ingest, upload, list, search, ask, off-topic ask, stream, delete (204, then 404). The only differences were two example values (`characters`, a search score), corrected to the real output. |
| 6 | Live streaming | `curl -N` against Gemini on a real `uvicorn` server: `sources`, then separate `token` events arriving over about 2 seconds, then `done` (Task 9, and again in the README run). |
| 7 | Delete removes from list and search | Live in the README run: after `DELETE /documents/leave-policy`, `GET /documents` listed only `team-notes`, and `/search` returned only `team-notes`. Tests: `test_deleted_document_is_gone_from_search`, `test_delete_returns_204_and_removes_every_chunk`. |
| 8 | Docker healthy, data survives restart | Task 10: container healthy about 30 s after start, running as non-root `sourcely`; ingest, search and a live `/ask` worked; after `docker compose restart`, `chunks_indexed` was unchanged and the model wasn't downloaded again. |

Not verified live: the Anthropic (Claude) path, because no key was available. It is covered by unit tests against the installed SDK's request shape, and the README says so.

## Out of scope (possible next steps)

Auth, PDF and DOCX parsing, pagination for `GET /documents`, range and `$or` filters, hybrid (BM25 plus vector) search, reranking, an evaluation harness, and a Qdrant backend.

## Open questions

1. `MIN_RELEVANCE` will be set from measured scores. bge-small often gives unrelated text around 0.4 to 0.5 similarity, so the value needs data. First measurement (Task 4 live check, 3 short documents, 2026-09-18): the right document scored 0.67 to 0.71, unrelated documents 0.40 to 0.63, and an off-topic question's best hit 0.475. The ranges overlap, so the threshold must come from a larger sample at Checkpoint B.

   **Resolved at Checkpoint B (2026-09-19).** Corpus: 6 policy documents, 14 questions they answer and 8 they don't. Top-1 accuracy was 13 of 14 with or without the prefix. Without the prefix, the right document scored 0.609 to 0.824 and unanswerable questions' best hit reached 0.589 (gap 0.020). With bge's query prefix, 0.607 to 0.794 against at most 0.555 (gap 0.052). The owner chose the prefix and `MIN_RELEVANCE = 0.58`, the middle of the gap: all 8 unanswerable questions blocked, all 14 answerable ones kept. The old default of 0.5 let 5 of 8 through. The sample is small; recheck on real pilot documents.
