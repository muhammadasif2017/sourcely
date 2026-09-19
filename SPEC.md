# Spec: Sourcely

## Objective

Build a small backend that answers questions from documents a client has uploaded. It runs the full retrieval-augmented generation (RAG) flow:

```
Document -> Chunks -> Embeddings -> Vector store -> Semantic search -> Retrieved context -> LLM answer
```

The users are developers who evaluate or extend the service over HTTP. There is no frontend.

**Versions.** The proof of concept (Tasks 1 to 11) is tagged `v0.1.0`: no auth, one shared index in ChromaDB. **Phase 1** (approved 2026-09-19, see [Phase 1](#phase-1-accounts-workspaces-and-api-keys) at the end) adds accounts, workspaces and API keys, and moves storage to PostgreSQL with pgvector. Where Phase 1 changes something described earlier in this file, the Phase 1 section wins.

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
| Vector store | ChromaDB `PersistentClient`, cosine space, on disk at `CHROMA_PATH`. **Replaced by pgvector in Phase 1.** | Embedded, so no server or Docker. Persists across restarts. |
| Embeddings | Local `fastembed`, `BAAI/bge-small-en-v1.5` (384 dimensions) | No key, no cost. Claude has no embeddings API. |
| Generation | `LLM_PROVIDER=openai` (default) or `anthropic` (`claude-opus-5`). The `openai` provider accepts `OPENAI_BASE_URL`, so it can also talk to any OpenAI-compatible server. | The client asked for "OpenAI or Claude", and both work by changing `.env` alone. The developer has no paid keys, so development runs free on Gemini. |
| Development LLM | Gemini `gemini-3.5-flash-lite` through Google's OpenAI-compatible endpoint, on the free tier | Verified live on 2026-09-18: 1.6s, 12 tokens for a trivial call. `gemini-2.5-*` now returns 404 for new users. The version is pinned rather than the `-latest` alias, so results stay reproducible. Ollama `qwen2.5:3b` is the offline fallback. |
| Claude refusals | `fallbacks="default"` with beta `server-side-fallback-2026-07-01` | Recommended default for `claude-opus-5`. A remaining refusal becomes a 502. |
| Chunking | Recursive character splitter: paragraph, then line, then sentence, then word, then a hard cut. Configurable size and overlap. | Keeps chunks on natural boundaries. No LangChain dependency. |
| Python | 3.12, pinned in `.python-version` | The system Python 3.14 lacks reliable ONNX runtime wheels. |

## Tech stack

Python 3.12, FastAPI 0.141, Uvicorn, Pydantic 2 plus pydantic-settings, chromadb 1.5, fastembed 0.8, anthropic 1.6, openai 3.15, python-multipart. Dev tools: pytest, httpx, ruff. Package manager: uv.

**Phase 1 adds** (approved with decisions D1 to D3): SQLAlchemy 2 (sync), psycopg 3 (binary), Alembic, pgvector (Python package), argon2-cffi and email-validator. It removes chromadb once `PgVectorStore` has passed its parity check. The database is PostgreSQL 17 with the pgvector extension (Docker image `pgvector/pgvector:pg17`).

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

PDF and DOCX parsing, pagination for `GET /documents`, range and `$or` filters, hybrid (BM25 plus vector) search, reranking, an evaluation harness, and a Qdrant backend.

## Open questions

1. `MIN_RELEVANCE` will be set from measured scores. bge-small often gives unrelated text around 0.4 to 0.5 similarity, so the value needs data. First measurement (Task 4 live check, 3 short documents, 2026-09-18): the right document scored 0.67 to 0.71, unrelated documents 0.40 to 0.63, and an off-topic question's best hit 0.475. The ranges overlap, so the threshold must come from a larger sample at Checkpoint B.

   **Resolved at Checkpoint B (2026-09-19).** Corpus: 6 policy documents, 14 questions they answer and 8 they don't. Top-1 accuracy was 13 of 14 with or without the prefix. Without the prefix, the right document scored 0.609 to 0.824 and unanswerable questions' best hit reached 0.589 (gap 0.020). With bge's query prefix, 0.607 to 0.794 against at most 0.555 (gap 0.052). The owner chose the prefix and `MIN_RELEVANCE = 0.58`, the middle of the gap: all 8 unanswerable questions blocked, all 14 answerable ones kept. The old default of 0.5 let 5 of 8 through. The sample is small; recheck on real pilot documents.

---

# Phase 1: accounts, workspaces and API keys

Approved on 2026-09-19. Product background: [`docs/product/PRD.md`](docs/product/PRD.md) (features F1, F2, F10), [`docs/product/ARCHITECTURE.md`](docs/product/ARCHITECTURE.md) and [`docs/product/FLOW_DIAGRAMS.md`](docs/product/FLOW_DIAGRAMS.md) (FD-2, FD-9, FD-10, FD-12). Tasks are in `tasks/todo.md`, Phase 5.

## Goal

Several teams can use one Sourcely deployment without seeing each other's data. People sign up and sign in; each document, chunk and API key belongs to exactly one **workspace**; and every data request is authenticated and scoped to one workspace. The PoC endpoints keep their paths and bodies.

**Exit criterion:** two workspaces on one deployment can't read each other's documents, search results or answers, proven by automated tests at the HTTP level and at the database level.

## Decisions

| Concern | Decision | Why |
|---|---|---|
| D1 Authentication | Built in: email and password, Argon2id hashes (argon2-cffi), server-side sessions in Postgres | Self-hostable with no outside account; the scope is small and well understood |
| D2 Database | PostgreSQL 17, SQLAlchemy 2 (sync, psycopg 3), Alembic migrations | Row-level security and the vector index need Postgres. Sync matches the existing `def` routes. |
| D3 Vector store | pgvector in the same database, behind the existing `VectorStore` interface | One database and one backup; deletes of documents and vectors in one transaction; row-level security covers vectors too |
| Email | An `EmailSender` protocol. Phase 1 ships `ConsoleEmailSender`, which writes each email (recipient, subject, token, link) to the log. `EMAIL_BACKEND=console` is the only value. | Sign-up can be tested with no mail account. A real sender plugs in later without route changes. |
| PoC data | Not migrated. The `v0.1.0` Chroma index held test data only; documents are re-ingested into a workspace. | Keeps the migration path simple. |
| Migrations | Locally: `uv run alembic upgrade head`. In Compose: a one-shot `migrate` service that must finish before `api` starts. | The app never alters the schema at startup. |

## Database roles and isolation

Two roles, created by `docker/postgres/init.sql` in Compose and by the test fixtures otherwise:

- `sourcely_owner` owns the schema and runs migrations (`MIGRATION_DATABASE_URL`).
- `sourcely_app` is what the API connects as (`DATABASE_URL`). It can read and write rows but owns no table, so it **cannot bypass row-level security**.

Isolation has three layers:

1. **Request.** Authentication resolves exactly one `Principal` per request: `(user_id or api_key_id, workspace_id, role)`. No route reads a workspace id from the request body.
2. **Code.** Every repository and vector-store function that touches tenant data takes `workspace_id` as a required argument.
3. **Database.** `documents` and `chunks` have row-level security: `USING (workspace_id = current_setting('app.workspace_id', true)::uuid)`. The API runs `SET LOCAL app.workspace_id = ...` at the start of each request's transaction. With the setting missing, no tenant rows are visible.

Tables used to *find* the workspace (`sessions`, `memberships`, `api_keys`, `invites`) are read before a workspace is known, so they are protected by layers 1 and 2, not by row-level security.

## Data model (Alembic migration `0001` onward)

| Table | Key columns |
|---|---|
| `users` | `id` uuid PK, `email` citext unique, `name`, `password_hash`, `email_verified_at`, `created_at` |
| `sessions` | `token_hash` bytea PK (SHA-256 of the cookie value), `user_id` FK, `csrf_token`, `created_at`, `last_seen_at`, `expires_at` |
| `email_tokens` | `token_hash` PK, `user_id` FK, `purpose` (`verify` or `reset`), `expires_at`, `used_at` |
| `login_attempts` | `email`, `attempted_at`: failed sign-ins, for throttling |
| `workspaces` | `id` uuid PK, `name`, `created_at` |
| `memberships` | PK (`workspace_id`, `user_id`), `role` (`owner`, `admin`, `editor`, `viewer`), `created_at`. Exactly one `owner` per workspace. |
| `invites` | `id` PK, `workspace_id` FK, `email`, `role`, `token_hash`, `invited_by`, `expires_at`, `accepted_at` |
| `api_keys` | `id` PK, `workspace_id` FK, `name`, `prefix` (first 12 characters), `key_hash`, `created_by`, `created_at`, `last_used_at`, `revoked_at` |
| `documents` | PK (`workspace_id`, `document_id`), `title`, `metadata` jsonb, `created_at`, `updated_at`. `document_id` keeps the PoC pattern and is unique per workspace. |
| `chunks` | PK (`workspace_id`, `document_id`, `chunk_index`), FK (`workspace_id`, `document_id`) to `documents` with cascade delete, `text`, `embedding` `vector(384)` with an HNSW index (`vector_cosine_ops`) |

Deleting a workspace cascades to its memberships, invites, API keys, documents and chunks. `GET /documents` now reads the `documents` table, which removes the PoC's O(chunks) listing cost.

## Vector store on pgvector

`PgVectorStore` implements the same methods as the Chroma `VectorStore` (`replace_document`, `query`, `list_documents`, `delete_document`, `count`), each with a `workspace_id` argument.

- **Score.** `score = 1 - (embedding <=> query)`: cosine distance, exactly as in the PoC, so `MIN_RELEVANCE` keeps its meaning.
- **Filters.** `document_ids` become `document_id = ANY(...)`. Each metadata pair becomes JSONB containment (`metadata @> {"key": value}`), which keeps exact, typed matching: `2026` and `"2026"` still differ.
- **Filtered searches still return up to `top_k` matches.** Queries use pgvector's iterative index scan (`hnsw.iterative_scan`), or an exact scan, so a filter can't empty the result when matching chunks exist further down.
- **Replace is atomic.** Deleting a document's old chunks and inserting the new ones happen in one transaction, which closes the PoC's "not fully atomic" gap.
- **Settled in Task 16.** The policy compares `workspace_id` with `NULLIF(current_setting('app.workspace_id', true), '')::uuid`: on a pooled connection a finished `set_config(..., true)` leaves an empty string, not NULL, and `''::uuid` would be an error. `/health` counts chunks through `chunk_count()`, a `SECURITY DEFINER` function owned by `sourcely_owner` that returns only the number. Routes get the store through `IndexDep`, which sets the workspace on the transaction and returns a `WorkspaceIndex` bound to it.
- **Parity gate: passed on 2026-09-19.** `scripts/calibrate.py` on `PgVectorStore` gave the same scores as Chroma to three decimals for all 22 questions: top-1 13 of 14, and at `MIN_RELEVANCE = 0.58` with the prefix, 14 of 14 kept and 8 of 8 blocked. The threshold is unchanged, and `chromadb` was removed.
- **Parity gate before Chroma is removed.** `scripts/calibrate.py` runs against `PgVectorStore` and must give the same outcome as Chroma: top-1 13 of 14, and at `MIN_RELEVANCE = 0.58` all 14 answerable questions kept and all 8 unanswerable ones blocked. If not, the threshold is recalibrated and this section updated before continuing.

## Authentication

**Browser sessions.** Signing in sets two cookies:

- `sourcely_session`: a random 32-byte token. `HttpOnly`, `SameSite=Lax`, and `Secure` unless `COOKIE_SECURE=false` (only for plain-HTTP local development and tests). Only its SHA-256 hash is stored. A session expires after `SESSION_IDLE_DAYS` (14) without use, and is deleted on sign-out and on password reset.
- `sourcely_csrf`: readable by JavaScript. Every `POST`, `PATCH`, `PUT` and `DELETE` made with a session must send the same value in `X-CSRF-Token`, or gets 403. This is the double-submit pattern.

A session request that touches workspace data names the workspace in the **`X-Workspace-ID`** header. Without it: 400. For a workspace the user isn't a member of: 404.

**Settled in Task 15.** A key request may send `X-Workspace-ID`; if it names another workspace, 400. A bad, unknown or revoked key is 401 "Invalid or revoked API key". A key on a session-only endpoint is 403 "This needs a signed-in user; API keys can't be used here". Both credentials together are 400 "Send either a session cookie or an API key, not both". Revoking an already revoked key is 204 and keeps the first revocation time; another workspace's key is 404. Keys are listed newest first, revoked ones included. `created_by` becomes null if the creating user is deleted; the key keeps working, because it belongs to the workspace.

**API keys.** `Authorization: Bearer sk_live_<43 random base64url characters>`. Only the SHA-256 hash and the first 12 characters are stored. A key acts on its own workspace with the **editor** role. It can't call `/auth/*`, `/me`, or workspace, member, invite or key management (403). CSRF doesn't apply to keys, because they aren't cookies. A request that sends both a session cookie and a key gets 400.

**Passwords.** 12 to 128 characters, and not on the bundled list of common passwords (`app/core/common_passwords.txt`: the 1,259 entries of 12 or more characters from the UK NCSC's 100,000 most-used passwords, compared case-insensitively). A generic 10,000-entry list would add almost nothing: only 10 of its entries are 12 characters or longer. Hashed with Argon2id. After 5 failed sign-ins for one email within 15 minutes, further attempts get 429 with `Retry-After`, even with the right password. Sign-in failures always say "Email or password is incorrect", for an unknown email too, and take about the same time (a dummy hash is checked when the email doesn't exist).

**Tokens.** Email verification (24 hours), password reset (1 hour) and invites (7 days) use 32 random bytes; only hashes are stored; each works once.

**Settled in Task 13.** Emails are stored lowercased and compared case-insensitively (`citext`). Response texts: sign-up `202 {"detail": "Check your email to finish signing up"}`; reset request `202 {"detail": "If that email has an account, we sent a reset link"}`; a bad email link `400 "This link is invalid or has expired"`; bad credentials `401 "Email or password is incorrect"`; no session `401 "Not signed in"`; CSRF `403 "Missing or invalid CSRF token"`; throttled `429 "Too many failed sign-ins. Try again later."` with `Retry-After` in seconds until the oldest failure leaves the 15-minute window. A successful sign-in clears that email's failures. A password reset also marks the email verified, since the link proves control of the address. Password rules apply only when a password is set, never at sign-in. Emails link to `APP_BASE_URL/verify-email?token=...` and `APP_BASE_URL/reset-password?token=...`, pages of the future web app; until then the token is used with the API directly.

## Roles

| Action | owner | admin | editor | viewer | API key |
|---|:-:|:-:|:-:|:-:|:-:|
| `GET /documents`, `POST /search`, `POST /ask`, `POST /ask/stream` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `POST /documents`, `POST /documents/upload`, `DELETE /documents/{id}` | ✓ | ✓ | ✓ | | ✓ |
| Rename workspace, list and manage members, invites and API keys | ✓ | ✓ | | | |
| Delete workspace, transfer ownership | ✓ | | | | |

Admins can only assign or change roles below their own. Nobody can remove or demote the owner except through ownership transfer. A role failure inside the caller's own workspace is 403.

## API additions

The PoC paths and bodies don't change. Every PoC endpoint except `GET /health` now requires a session (with `X-Workspace-ID`) or an API key, and works only on that workspace's data.

| Method and path | Auth | Request | Success |
|---|---|---|---|
| `POST /auth/signup` | none | `{name, email, password}` | 202, the same body whether or not the email exists. A new user gets a verification email; an existing one gets a "you already have an account" email. |
| `POST /auth/verify` | none | `{token}` | 200 `{user}`, signs in (sets cookies). 400 if the token is invalid, used or expired. |
| `POST /auth/login` | none | `{email, password}` | 200 `{user}`, sets cookies. 401 generic, 403 "Email not verified", 429 throttled. |
| `POST /auth/logout` | session | none | 204. The session is deleted and the cookies cleared. |
| `POST /auth/password-reset` | none | `{email}` | 202, the same body whether or not the email exists |
| `POST /auth/password-reset/confirm` | none | `{token, password}` | 204. Every session of that user is deleted. |
| `GET /me` | session | none | 200 `{user: {id, name, email}, workspaces: [{id, name, role}]}` |
| `POST /workspaces` | session | `{name}` | 201 `{id, name, role: "owner"}` |
| `PATCH /workspaces/{workspace_id}` | session, admin | `{name}` | 200 `{id, name}` |
| `DELETE /workspaces/{workspace_id}` | session, owner | `{confirm_name}` must equal the name | 204, deletes everything in it |
| `POST /workspaces/{workspace_id}/transfer` | session, owner | `{user_id}` of a member | 200. The new owner becomes `owner`, the old one `admin`. |
| `GET /workspaces/{workspace_id}/members` | session, admin | none | 200 `{members: [{user_id, name, email, role}]}` |
| `PATCH /workspaces/{workspace_id}/members/{user_id}` | session, admin | `{role}` | 200 |
| `DELETE /workspaces/{workspace_id}/members/{user_id}` | session, admin | none | 204. A member can also remove themself, except the owner. |
| `POST /workspaces/{workspace_id}/invites` | session, admin | `{emails: [1 to 20], role}` | 201 `{invites: [{id, email, role, expires_at}]}`. An email is sent for each. |
| `GET /workspaces/{workspace_id}/invites` | session, admin | none | 200, pending invites |
| `DELETE /workspaces/{workspace_id}/invites/{invite_id}` | session, admin | none | 204 |
| `POST /invites/accept` | session | `{token}` | 200 `{workspace_id, role}`. 410 if missing, used or expired. 409 if signed in as a different email. |
| `POST /workspaces/{workspace_id}/api-keys` | session, admin | `{name}` | 201 `{id, name, prefix, key, created_at}`. `key` is shown only here. |
| `GET /workspaces/{workspace_id}/api-keys` | session, admin | none | 200, keys without the secret, with `last_used_at` and `revoked_at` |
| `DELETE /workspaces/{workspace_id}/api-keys/{key_id}` | session, admin | none | 204. The key stops working immediately. |

**Settled in Task 14.** Workspace names are 1 to 60 characters after trimming. `/me` lists workspaces sorted by name, ignoring case. A malformed workspace id, in the path or the header, is 404 like an unknown one. `POST /workspaces/{id}/transfer` returns `200 {"owner_user_id": ...}`, 400 "You already own this workspace" for the caller themself, and 404 "Member not found" for a non-member. A wrong `confirm_name` on delete is 400 "Type the workspace name exactly to confirm". A role failure is 403 "Your role in this workspace doesn't allow this". The one-owner rule is a partial unique index (`uq_memberships_one_owner`), so the database itself refuses a second owner.

**Settled in Task 17.** Members are listed owner first, then by role, then by name. A role change answers `200 {user_id, role}`; `owner` isn't an assignable role (422). The caller may only change members ranked below them, and only to a role below their own; the owner's role changes only by transfer; each refusal is 403 with a reason. Any member except the owner may remove themself (leave). Invite emails are lowercased and deduplicated; inviting someone already in the workspace is 409 "Already a member: <email>"; a new invite to the same address replaces the pending one, so only the latest link works. Revoking deletes the invite. Accepting when already a member keeps the current role, so an invite can never lower a role. Invite links point to `APP_BASE_URL/invites/accept?token=...`.

Workspace management endpoints take the workspace from the path, not from `X-Workspace-ID`. A workspace the caller doesn't belong to is always **404**, never 403, so its existence isn't revealed.

`GET /health` stays public. Its `chunks_indexed` becomes the deployment-wide chunk count, and it adds `database: "ok"` or returns 503 `Database unavailable` when the database is unreachable. Database connections time out after 5 seconds, so an outage can't stall requests or health checks.

### Error table additions

| Condition | Status |
|---|---|
| No credential, or an invalid, expired or revoked one | 401 |
| Missing `X-Workspace-ID` on a session data request, or both a cookie and a key | 400 |
| Missing or wrong `X-CSRF-Token` on a session write | 403 |
| Role too low, or an API key on a management endpoint | 403 |
| Workspace or resource in another workspace | 404 |
| Invite for a different email than the signed-in user | 409 |
| Invite missing, used or expired | 410 |
| Too many failed sign-ins | 429 with `Retry-After` |
| Database unreachable | 503 |

## Configuration additions

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://sourcely_app:sourcely_app@127.0.0.1:5434/sourcely` (host port 5434, and `127.0.0.1` rather than `localhost`, which tries IPv6 first and stalls for 15 s on Windows) |
| `MIGRATION_DATABASE_URL` | `postgresql+psycopg://sourcely_owner:sourcely_owner@127.0.0.1:5434/sourcely` |
| `EMBEDDING_DIM` | `384`. Must match the model and the `vector(...)` column; checked at startup. |
| `TEST_ADMIN_DATABASE_URL` | Tests only: `postgresql+psycopg://postgres:postgres@127.0.0.1:5434/postgres`, a superuser connection used to create and drop the per-run test database |
| `COOKIE_SECURE` | `true` |
| `SESSION_IDLE_DAYS` | `14` |
| `EMAIL_BACKEND` | `console` |
| `APP_BASE_URL` | `http://localhost:8000`, used to build links in emails |

`CHROMA_PATH` and `COLLECTION_NAME` were removed with Chroma in Task 16.

## Testing

- **A real Postgres is required for most tests.** Row-level security and pgvector can't be imitated with SQLite. Locally: `docker compose up -d db`. In CI: a `pgvector/pgvector:pg17` service container.
- A session fixture creates a fresh database per test run, runs the migrations as the owner, and makes sure the `sourcely_app` role exists. Each test starts from truncated tables. Pure unit tests still need no database.
- **Existing tests keep their shape.** The `client` fixture creates a user, a workspace and an API key, and sends the key on every request, so the 233 PoC tests exercise the authenticated paths unchanged. The fake embedder produces 384-dimension vectors to fit the column.
- **Cross-tenant tests are generated from the route table.** One parametrized test walks `app.routes` and calls every workspace-scoped route with workspace B's credentials against workspace A's resources, expecting 404 or an empty result. A route added later is covered automatically.
- **Database-level isolation test.** Connected as `sourcely_app` with `app.workspace_id` set to workspace B, a raw `SELECT` on `documents` and `chunks` returns none of workspace A's rows.
- Tests never call paid APIs or download models, as before.

## Success criteria

1. `uv run pytest -q` passes against Postgres, ruff and mypy are clean, and CI passes with the Postgres service.
2. Two workspaces on one deployment: none of A's documents appear in B's list, search, ask or stream, at the HTTP level (generated tests) and at the database level (raw `SELECT` as `sourcely_app`).
3. A live run with curl: sign up, read the token from the log, verify, create a workspace, ingest, then ask with the session cookie, CSRF token and `X-Workspace-ID`; then create an API key and ask with it.
4. The pgvector parity gate passes, or `MIN_RELEVANCE` is recalibrated and recorded.
5. Passwords and every token are stored only as hashes. The sign-in throttle returns 429 after 5 failures.
6. `docker compose up --build` starts `db`, runs `migrate`, and serves a healthy `api`. Data survives a restart.

## Out of scope for Phase 1

The web interface (Phase 2), a real email sender, Google sign-in, PDF and DOCX, conversations, feedback, usage insights, quotas, and an audit log. The PoC's Chroma data is not migrated.
