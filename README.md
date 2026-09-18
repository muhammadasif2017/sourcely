# Sourcely

Sourcely is a small backend that answers questions from your own documents and shows where each answer came from. You upload text, and Sourcely splits it into chunks, embeds them locally and stores them in a vector database. When you ask a question, it finds the most relevant chunks and has an LLM answer from them, with citations like `[1]`. If no stored text is relevant enough, it says so instead of guessing, without calling the LLM.

```
Document -> Chunks -> Embeddings -> Vector store -> Semantic search -> Retrieved context -> LLM answer
```

It is a proof of concept built with FastAPI. The API contract, decisions and limits are in [`SPEC.md`](SPEC.md).

- **Local embeddings.** `BAAI/bge-small-en-v1.5` runs on your CPU through fastembed. Ingest and search cost nothing and need no key.
- **Any LLM through configuration.** Google Gemini (free tier), OpenAI, Claude or a local Ollama model, chosen in `.env` with no code change.
- **Honest answers.** Every answer cites its sources. Questions the documents don't cover get a fixed "not enough information" answer.
- **Streaming.** `/ask/stream` sends the answer as it is written, using Server-Sent Events.

## Contents

1. [Quick start with Docker](#quick-start-with-docker)
2. [Quick start with uv](#quick-start-with-uv)
3. [Getting a free Gemini key](#getting-a-free-gemini-key)
4. [Choosing an LLM provider](#choosing-an-llm-provider)
5. [Using the API](#using-the-api)
6. [Configuration](#configuration)
7. [Architecture](#architecture)
8. [Development](#development)
9. [Known limits](#known-limits)
10. [Next steps](#next-steps)

> **Free-tier data warning.** On Gemini's free tier, Google may use your prompts and responses, including the document passages Sourcely sends with each question, to improve its products. Don't ingest confidential text while using a free-tier key. Use a paid provider, or local Ollama, for private documents.

## Quick start with Docker

You need [Docker](https://docs.docker.com/get-docker/) with Compose. No local Python is required.

```bash
cp .env.example .env          # then put your Gemini key in OPENAI_API_KEY (see below)
docker compose up --build     # first start downloads the embedding model, about 65 MB
```

The API is at <http://localhost:8000>, with interactive docs at <http://localhost:8000/docs>. The container reports itself healthy once `/health` responds, usually within a minute.

Stored documents and the model cache live in Docker volumes, so they survive restarts and rebuilds. Stop with `Ctrl+C` or `docker compose down`. To also delete the stored documents and the model cache, run `docker compose down -v`.

## Quick start with uv

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the pinned Python 3.12 by itself.

```bash
uv sync                       # install the exact locked versions
cp .env.example .env          # then put your Gemini key in OPENAI_API_KEY
uv run uvicorn app.main:create_app --factory --reload
```

Open <http://localhost:8000/docs>. The first start downloads the embedding model into `data/models/`. Documents are stored in `data/chroma/`.

Always start the server with `--factory`. There is deliberately no module-level `app`, so `uvicorn app.main:app` won't work.

> **Windows:** the commands above work in Git Bash. In PowerShell, use `Copy-Item .env.example .env` instead of `cp`, and `curl.exe` instead of `curl` for the examples below.

> **Environment variables win over `.env`.** If your shell already has `OPENAI_API_KEY` set, for example for another project, it replaces the value in `.env` without any warning. Unset it for this shell, or start a clean one.

## Getting a free Gemini key

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a Google account.
2. Click **Create API key**. Keys start with `AIza` or, for newer keys, `AQ.`.
3. Paste it into `.env`:

   ```
   OPENAI_API_KEY=your-key-here
   ```

The variable is called `OPENAI_API_KEY` because Sourcely talks to Gemini through Google's OpenAI-compatible endpoint, using the same client as OpenAI. The rest of the Gemini setup is already active in `.env.example`.

Without any key, the server still starts: `/documents` and `/search` work, and `/ask` returns `503 LLM provider not configured`.

## Choosing an LLM provider

Edit `.env`, restart the server, and check `GET /health`: it reports the active `llm_provider`, `llm_model` and whether a key is set (`llm_configured`). `.env.example` has a ready block for each option.

| Provider | Settings | Notes |
|---|---|---|
| **Google Gemini** (default, free tier) | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `OPENAI_API_KEY=<Gemini key>`, `OPENAI_MODEL=gemini-3.5-flash-lite` | Verified live. See the data warning above. |
| **OpenAI** | `LLM_PROVIDER=openai`, remove `OPENAI_BASE_URL`, `OPENAI_API_KEY=sk-...`, `OPENAI_MODEL=gpt-5-mini` | Same code path as Gemini, pointed at api.openai.com. |
| **Claude** (Anthropic) | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=sk-ant-...`, `ANTHROPIC_MODEL=claude-opus-5` | Uses server-side refusal fallbacks (`fallbacks="default"`). **Not verified live:** no Anthropic key was available, so this path is covered by unit tests against the installed SDK's request shape. |
| **Ollama** (local, free) | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODEL=qwen2.5:3b` | Run `ollama serve` and `ollama pull qwen2.5:3b` first. Nothing leaves your machine. Slower on CPU and lower quality. From Docker, use `http://host.docker.internal:11434/v1`. |

Embeddings stay local whichever LLM you choose, so switching providers never requires re-ingesting documents.

## Using the API

Every response carries an `X-Request-ID` header. Send your own (letters, digits, `.`, `_`, `-`, up to 128 characters) to trace a call through the logs. Errors are JSON: `{"detail": "..."}`.

### Ingest text: `POST /documents`

```bash
curl -X POST http://localhost:8000/documents \
  -H "Content-Type: application/json" \
  -d '{"document_id": "leave-policy", "title": "Leave policy",
       "text": "Full-time employees get 21 days of paid annual leave per year. Part-time staff receive leave pro-rated to their contracted hours.",
       "metadata": {"source": "hr", "year": 2026}}'
```

```json
{"document_id": "leave-policy", "title": "Leave policy", "chunks": 1, "characters": 129}
```

`document_id`, `title` and `metadata` are optional. Sending an existing `document_id` replaces that document. Metadata is a flat map of up to 20 string, number or boolean values.

### Upload a file: `POST /documents/upload`

```bash
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@notes.md" -F "document_id=team-notes"
```

Accepts UTF-8 `.txt` and `.md` files. The file name becomes the title. Other types return 415.

### List documents: `GET /documents`

```bash
curl http://localhost:8000/documents
```

```json
{"documents": [{"document_id": "leave-policy", "title": "Leave policy", "chunks": 1, "metadata": {"source": "hr", "year": 2026}}]}
```

### Delete a document: `DELETE /documents/{document_id}`

```bash
curl -X DELETE http://localhost:8000/documents/leave-policy     # 204, or 404 if unknown
```

### Search: `POST /search`

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how many vacation days do I get", "top_k": 3}'
```

```json
{"query": "how many vacation days do I get",
 "results": [{"document_id": "leave-policy", "chunk_index": 0, "title": "Leave policy",
              "text": "Full-time employees get 21 days ...", "score": 0.65, "metadata": {"source": "hr", "year": 2026}}]}
```

`score` is cosine similarity: higher means closer in meaning. Search never calls the LLM.

**Filters** work on `/search`, `/ask` and `/ask/stream`. A chunk must match every filter given:

```json
{"query": "refund window", "filters": {"document_ids": ["refunds", "billing-faq"], "metadata": {"source": "wiki"}}}
```

### Ask: `POST /ask`

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Do part-time workers get holiday?"}'
```

```json
{"answer": "Yes, part-time staff receive annual leave pro-rated to their contracted hours [1].",
 "sources": [{"document_id": "leave-policy", "chunk_index": 0, "title": "Leave policy", "text": "...", "score": 0.71, "metadata": {}}],
 "provider": "openai", "model": "gemini-3.5-flash-lite"}
```

`[1]` refers to the first item in `sources`. When nothing relevant is stored, the answer is "There is not enough information in the indexed documents to answer this question." with empty `sources`, and no LLM call is made.

### Ask with streaming: `POST /ask/stream`

```bash
curl -N -X POST http://localhost:8000/ask/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Do part-time workers get holiday?"}'
```

```
event: sources
data: {"sources": [...], "provider": "openai", "model": "gemini-3.5-flash-lite"}

event: token
data: {"text": "Yes, part-time staff receive annual leave"}

event: token
data: {"text": " pro-rated to their contracted hours [1]."}

event: done
data: {}
```

`-N` turns off curl's buffering so you see the text arrive. Errors that happen before the first token return a normal HTTP status (502, 503 or 504). An error after that arrives as `event: error` with `{"detail": "..."}`, and the stream ends. Browsers can't use `EventSource` here because it only sends `GET`. Read the response body with `fetch` instead.

### Health: `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "chunks_indexed": 1, "embedding_model": "BAAI/bge-small-en-v1.5",
 "llm_provider": "openai", "llm_model": "gemini-3.5-flash-lite", "llm_configured": true}
```

### Error statuses

| Status | When |
|---|---|
| 400 | `Content-Length` header isn't a number |
| 404 | Deleting a document that doesn't exist |
| 413 | Document longer than `MAX_DOCUMENT_CHARS`, or request body larger than `MAX_REQUEST_BYTES` |
| 415 | Upload that isn't `.txt` or `.md` |
| 422 | Invalid input: blank text, bad id, bad metadata or filters, non-UTF-8 file, out-of-range `top_k` |
| 502 | The LLM provider rejected the request, refused, or returned nothing |
| 503 | No LLM key configured, or the provider is rate limited or overloaded |
| 504 | The LLM provider timed out or couldn't be reached |
| 500 | Unexpected server error. The details go to the log, never to the client. |

## Configuration

All settings are environment variables, read from `.env` when present. Real environment variables take priority over `.env`. Invalid combinations, such as `CHUNK_OVERLAP` not smaller than `CHUNK_SIZE`, stop the server at startup with a clear error.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible API) or `anthropic` |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | none, api.openai.com, `gpt-5-mini` | OpenAI-compatible provider |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | none, `claude-opus-5` | Claude |
| `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS` | `16000`, `120` | Answer length and provider timeout |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model |
| `EMBEDDING_QUERY_PREFIX` | bge's retrieval instruction | Added to queries only. Change it together with the model. |
| `EMBEDDING_CACHE_DIR`, `CHROMA_PATH`, `COLLECTION_NAME` | `./data/models`, `./data/chroma`, `documents` | Where the model and the index are stored |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | `800`, `120` | Chunk length and overlap, in characters |
| `MAX_DOCUMENT_CHARS`, `MAX_REQUEST_BYTES` | `200000`, `2097152` | Size limits |
| `DEFAULT_TOP_K` | `4` | Chunks retrieved when a request doesn't say |
| `MIN_RELEVANCE` | `0.58` | Minimum similarity for a chunk to be used in an answer |
| `LOG_LEVEL` | `INFO` | Log verbosity |

`MIN_RELEVANCE` was calibrated on measured scores for bge-small with the query prefix. The data is in `SPEC.md`, Open questions. Recalibrate it if you change the embedding model or the prefix.

## Architecture

```
app/
  main.py             create_app(): builds components, adds middleware, routes and error handlers
  api/
    middleware.py     Request id and access log; request body size limit
    deps.py           Hands routes the settings, embedder, store and LLM (tests swap in fakes)
    routes/           health, documents, search, ask
  core/               Settings, errors, logging
  schemas/            Pydantic request and response models
  services/
    chunking.py       Splits text on paragraph, line, sentence and word boundaries, with overlap
    embeddings.py     Local fastembed model
    ingestion.py      Chunk, embed and store a document
    vector_store.py   ChromaDB collection: store, query, list, delete, filters
    llm.py            Prompt building, OpenAI-compatible and Anthropic adapters, error mapping
    rag.py            Retrieve, apply the relevance gate, answer or stream
```

How a question is answered:

1. The question is embedded with the same local model as the documents.
2. ChromaDB returns the `top_k` nearest chunks by cosine similarity, within any filters.
3. Chunks scoring below `MIN_RELEVANCE` are dropped. If none are left, the fixed answer is returned and the LLM is not called.
4. The remaining chunks go into the prompt as numbered `<source>` blocks. The system prompt tells the model to use only those sources, cite them as `[n]`, say when they don't contain the answer, and treat them as data rather than instructions.
5. The answer is returned with the sources, or streamed as events.

Routes stay thin and logic lives in `services/`. Components are created once at startup and injected, which is how the tests run without network access or model downloads. Design reasons for each technology are in [`docs/TECH_STACK.md`](docs/TECH_STACK.md).

## Development

```bash
uv run pytest -q                                      # tests: no network, no model downloads
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run mypy                                           # strict type checking
uv run pre-commit install                             # once: run the checks on every commit
```

GitHub Actions runs lint, type checks and tests on every push and pull request.

More documentation:

| File | What's in it |
|---|---|
| [`SPEC.md`](SPEC.md) | API contract, configuration, decisions, success criteria |
| [`CLAUDE.md`](CLAUDE.md) | Conventions, commands and verified gotchas for working in this repo |
| [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) | Step-by-step record of how the project was built, and why |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | Why each technology was chosen, with alternatives and limits |
| [`docs/INTERVIEW_PREP.md`](docs/INTERVIEW_PREP.md) | Questions about the design, with answers tied to the code |
| [`docs/product/`](docs/product/README.md) | Product plan beyond the PoC: PRD, wireframes, flows, architecture |

## Known limits

- **One server process for the index.** Embedded ChromaDB lives inside the API process, so the API can't run as several replicas sharing one index. The fix is a server-based vector store.
- **No authentication or rate limiting.** Anyone who can reach the API can read and change its documents. Don't expose it publicly as is.
- **Text formats only.** Uploads accept `.txt` and `.md`, not PDF or DOCX.
- **`GET /documents` reads every chunk's metadata.** It slows down as the number of chunks grows, and there's no pagination.
- **Exact-match filters only.** No ranges and no OR.
- **The relevance threshold rests on a small sample.** `0.58` came from 22 test questions. Recheck it on your own documents.
- **English-oriented embeddings.** bge-small-en is trained on English.
- **Claude is untested live.** The Anthropic adapter follows the installed SDK and has unit tests, but no live call was made.
- **The Docker image is large** (about 840 MB), mostly onnxruntime and chromadb.

## Next steps

- PDF and DOCX ingestion, processed in the background
- Hybrid search (keyword BM25 plus vectors) and a reranker, measured against an evaluation set
- Authentication, per-client rate limits and multi-tenant workspaces
- A shared vector store (pgvector or Qdrant) so the API can scale out
- A web interface

The product plan in [`docs/product/`](docs/product/README.md) develops these into phases.
