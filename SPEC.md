# Spec: RAG API (proof of concept)

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
- `title`: optional, at most 200 characters.
- `metadata`: optional flat map with at most 20 keys. Keys match `^[A-Za-z][A-Za-z0-9_]{0,63}$`. The server reserves `document_id`, `chunk_index` and `title`, and rejects them with 422. Values are str, int, float or bool, because Chroma stores only scalar values.

Response **201**:

```json
{ "document_id": "…", "title": "…", "chunks": 7, "characters": 5123 }
```

### `POST /documents/upload`: ingest a `.txt` or `.md` file (multipart)

The request has a `file` field and an optional `document_id` field. The server decodes the file as UTF-8, uses the filename as the default title, then follows the same rules as `POST /documents`. Any other file extension returns **415**. A file that is not valid UTF-8 returns **422**.

### `GET /documents`: list documents

Returns **200** `{ "documents": [ { "document_id": "…", "title": "…", "chunks": 7, "metadata": {} } ] }`, sorted by `document_id`. The server builds the list by reading chunk metadata, so its cost grows with the number of chunks. That is acceptable for a PoC and noted as a scaling limit.

### `DELETE /documents/{document_id}`: delete a document

Removes every chunk of that document. Returns **204** when the document existed and **404** when it did not.

### `POST /search`: semantic search

Request: `{ "query": "…", "top_k": 4, "filters": { "document_ids": ["a", "b"], "metadata": { "source": "wiki" } } }`. The query is 1 to 2,000 characters. `top_k` is 1 to 20 and defaults to `DEFAULT_TOP_K`.

`filters` is optional, and so is each of its fields:
- `document_ids`: 1 to 100 ids. A chunk matches when its document is in the list.
- `metadata`: 1 to 10 exact-match pairs with the same key and value rules as ingestion. A chunk must match every pair.

When both fields are present, a chunk must satisfy both. The server translates filters into a Chroma `where` clause (`$in`, `$eq`, `$and`).

Response **200**:

```json
{ "query": "…", "results": [ { "document_id": "…", "chunk_index": 0, "title": "…", "text": "…", "score": 0.82, "metadata": {} } ] }
```

`score` is cosine similarity (`1 - cosine distance`), sorted from highest to lowest. An empty store returns `results: []`, not an error.

### `POST /ask`: answer from retrieved context

Request: `{ "question": "…", "top_k": 4, "filters": { … } }`. It uses the same limits and filters as `/search`.

The server retrieves `top_k` chunks and drops any chunk that scores below `MIN_RELEVANCE`.

- **No chunks remain:** the server does not call the LLM. It returns **200** with a fixed "not enough information in the indexed documents" answer and `sources: []`.
- **Chunks remain:** the server builds a prompt with numbered context blocks and calls the configured LLM. It returns **200**:

```json
{ "answer": "… [1] …", "sources": [ /* the search hits that were used */ ], "provider": "anthropic", "model": "claude-opus-5" }
```

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
| `CHROMA_PATH` | `./data/chroma` |
| `COLLECTION_NAME` | `documents` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` characters. Overlap must be smaller than size. |
| `MAX_DOCUMENT_CHARS` | `200000` |
| `DEFAULT_TOP_K` | `4` |
| `MIN_RELEVANCE` | Calibrated against real bge-small scores during implementation, then recorded here. |
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

## Out of scope (possible next steps)

Auth, PDF and DOCX parsing, pagination for `GET /documents`, range and `$or` filters, hybrid (BM25 plus vector) search, reranking, an evaluation harness, and a Qdrant backend.

## Open questions

1. `MIN_RELEVANCE` will be set from measured scores. bge-small often gives unrelated text around 0.4 to 0.5 similarity, so the value needs data.
