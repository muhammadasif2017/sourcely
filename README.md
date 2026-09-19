# Sourcely

Sourcely answers questions from your team's documents and shows where each answer came from. You upload text, and Sourcely splits it into chunks, embeds them locally and stores them in PostgreSQL with pgvector. When you ask a question, it finds the most relevant chunks and has an LLM answer from them, with citations like `[1]`. If nothing stored is relevant enough, it says so instead of guessing, without calling the LLM.

```
Document -> Chunks -> Embeddings -> pgvector -> Semantic search -> Retrieved context -> LLM answer
```

- **Teams and workspaces.** People sign up, create workspaces and invite others with a role. Every document belongs to one workspace, and Postgres row-level security keeps workspaces apart.
- **Two ways in.** A browser session (cookie plus CSRF token), or an API key for your own tools.
- **Local embeddings.** `BAAI/bge-small-en-v1.5` runs on your CPU. Ingest and search cost nothing and need no key.
- **Any LLM through configuration.** Google Gemini (free tier), OpenAI, Claude or a local Ollama model.
- **Honest answers.** Every answer cites its sources, and questions the documents don't cover get a fixed "not enough information" answer.
- **Streaming.** `/ask/stream` sends the answer as it's written, using Server-Sent Events.

It's a FastAPI backend with no web interface yet. The contract is in [`SPEC.md`](SPEC.md). The proof of concept without accounts is tagged [`v0.1.0`](https://github.com/muhammadasif2017/sourcely/tree/v0.1.0).

## Contents

1. [Quick start with Docker](#quick-start-with-docker)
2. [Quick start with uv](#quick-start-with-uv)
3. [Your first answer](#your-first-answer)
4. [Getting a free Gemini key](#getting-a-free-gemini-key)
5. [Choosing an LLM provider](#choosing-an-llm-provider)
6. [Authentication](#authentication)
7. [API reference](#api-reference)
8. [Configuration](#configuration)
9. [Architecture](#architecture)
10. [Development](#development)
11. [Known limits](#known-limits)
12. [Next steps](#next-steps)

> **Free-tier data warning.** On Gemini's free tier, Google may use your prompts and responses, including the document passages Sourcely sends with each question, to improve its products. Don't ingest confidential text while using a free-tier key. Use a paid provider, or local Ollama, for private documents.

## Quick start with Docker

You need [Docker](https://docs.docker.com/get-docker/) with Compose. No local Python is needed.

```bash
cp .env.example .env          # then put your Gemini key in OPENAI_API_KEY (see below)
docker compose up --build
```

Compose starts three services:

| Service | What it does |
|---|---|
| `db` | PostgreSQL 17 with pgvector, published on `127.0.0.1:5434` |
| `migrate` | Runs the database migrations once, then exits |
| `api` | The API on <http://localhost:8000> (interactive docs at `/docs`), started after `migrate` succeeds |

The first start downloads the embedding model (about 65 MB); the API reports healthy once `/health` responds. Data lives in Docker volumes and survives restarts. `docker compose down` stops everything; `docker compose down -v` also deletes the data.

The Compose file sets `COOKIE_SECURE=false`, because it serves plain HTTP on localhost. Behind HTTPS, set it back to `true`, the default.

## Quick start with uv

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and Docker (for the database). uv installs the pinned Python 3.12 by itself.

```bash
uv sync                                  # install the exact locked versions
cp .env.example .env                     # then put your Gemini key in OPENAI_API_KEY
docker compose up -d db                  # PostgreSQL + pgvector on 127.0.0.1:5434
uv run alembic upgrade head              # create the schema
uv run uvicorn app.main:create_app --factory --reload
```

For local HTTP, add `COOKIE_SECURE=false` to `.env`, or browsers and curl won't send the session cookie back.

- Always start the server with `--factory`: there's deliberately no module-level `app`.
- Use `127.0.0.1` in database URLs, not `localhost`. On Windows, `localhost` tries IPv6 first and each connection stalls for about 15 seconds.
- Real environment variables override `.env`. If your shell already has `OPENAI_API_KEY` set for another project, it silently replaces the one in `.env`.
- **Windows:** the commands work in Git Bash. In PowerShell, use `Copy-Item` instead of `cp` and `curl.exe` instead of `curl`.

## Your first answer

There's no web interface yet, so this uses curl. The cookie jar file keeps your session between commands.

**1. Sign up.** Emails are written to the API's log rather than sent, so the verification link appears there.

```bash
curl -X POST http://localhost:8000/auth/signup -H "Content-Type: application/json" \
  -d '{"name": "Ayesha", "email": "ayesha@example.com", "password": "violet-anchor-tuesday-42"}'

docker compose logs api | grep -A5 "email to=ayesha@example.com"     # find token=...
```

**2. Verify.** This signs you in and saves the session and CSRF cookies.

```bash
curl -c jar.txt -b jar.txt -X POST http://localhost:8000/auth/verify \
  -H "Content-Type: application/json" -d '{"token": "PASTE_THE_TOKEN"}'
```

**3. Create a workspace and an API key.** Writes made with a session need the CSRF token in a header.

```bash
CSRF=$(grep sourcely_csrf jar.txt | awk '{print $7}')

curl -b jar.txt -X POST http://localhost:8000/workspaces \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" -d '{"name": "Acme Support"}'
# -> {"id": "7ee2497c-...", "name": "Acme Support", "role": "owner"}

curl -b jar.txt -X POST http://localhost:8000/workspaces/WORKSPACE_ID/api-keys \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" -d '{"name": "curl"}'
# -> {"key": "sk_live_...", ...}   shown only once: store it
```

**4. Add a document and ask.** From here on, the API key is all you need.

```bash
KEY=sk_live_...

curl -X POST http://localhost:8000/documents -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "leave", "title": "Leave policy",
       "text": "Full-time employees get 21 days of paid annual leave per year. Part-time staff receive annual leave pro-rated to their contracted hours."}'

curl -X POST http://localhost:8000/ask -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d '{"question": "Do part-time workers get holiday?"}'
# -> {"answer": "Yes, part-time staff receive annual leave pro-rated to their contracted hours [1].",
#     "sources": [{"document_id": "leave", ...}], "provider": "openai", "model": "gemini-3.5-flash-lite"}
```

## Getting a free Gemini key

1. Open [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a Google account.
2. Click **Create API key**. Keys start with `AIza` or, for newer keys, `AQ.`.
3. Put it in `.env` as `OPENAI_API_KEY=...`. The name is right: Sourcely talks to Gemini through Google's OpenAI-compatible endpoint, which `.env.example` already sets up.

Without any key the server still starts: everything works except `/ask` and `/ask/stream`, which return `503 LLM provider not configured`.

## Choosing an LLM provider

Edit `.env`, restart, and check `GET /health`, which reports `llm_provider`, `llm_model` and `llm_configured`. `.env.example` has a ready block for each option.

| Provider | Settings | Notes |
|---|---|---|
| **Google Gemini** (default, free tier) | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `OPENAI_API_KEY=<Gemini key>`, `OPENAI_MODEL=gemini-3.5-flash-lite` | Verified live. See the data warning above. |
| **OpenAI** | `LLM_PROVIDER=openai`, remove `OPENAI_BASE_URL`, `OPENAI_API_KEY=sk-...`, `OPENAI_MODEL=gpt-5-mini` | Same code path as Gemini. |
| **Claude** | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=sk-ant-...`, `ANTHROPIC_MODEL=claude-opus-5` | Uses server-side refusal fallbacks. **Not verified live** (no Anthropic key was available); covered by unit tests against the installed SDK. |
| **Ollama** (local, free) | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODEL=qwen2.5:3b` | Run `ollama serve` and `ollama pull qwen2.5:3b` first. Nothing leaves your machine. From Docker, use `http://host.docker.internal:11434/v1`. |

Embeddings stay local whichever LLM you choose, so switching providers never requires re-ingesting documents.

## Authentication

Every endpoint except `/health` and the sign-up and sign-in routes needs one of two credentials, never both at once (400):

| | API key | Browser session |
|---|---|---|
| Send | `Authorization: Bearer sk_live_...` | The `sourcely_session` cookie, from `/auth/verify` or `/auth/login` |
| Workspace | The key's own workspace | Name it in `X-Workspace-ID` on data requests |
| Writes | No extra header | `X-CSRF-Token` must equal the `sourcely_csrf` cookie |
| Role | Editor: read, search, ask, add and delete documents | Your role in the workspace |
| Can't | Manage the workspace, members, invites or keys; `/me` (403) | |

**Roles.** Viewers read, search and ask. Editors also add, replace and delete documents. Admins also rename the workspace and manage members, invites and API keys. The owner can also delete the workspace and transfer ownership. You can only give roles below your own, and only change members ranked below you.

**Security details.** Passwords are Argon2id hashes. Sessions, API keys and email and invite links are stored only as SHA-256 hashes. Sign-in is refused for 15 minutes after 5 failures for an email. Sign-up, sign-in and password reset answer the same way whether or not an email is registered.

## API reference

Interactive docs with every schema are at <http://localhost:8000/docs>. Each response carries an `X-Request-ID` header; send your own to trace a call through the logs. Errors are JSON: `{"detail": "..."}`.

### Accounts

| Method and path | Body | Result |
|---|---|---|
| `POST /auth/signup` | `{name, email, password}` | 202; a verification link by email |
| `POST /auth/verify` | `{token}` | 200 `{user}`; signs in |
| `POST /auth/login` | `{email, password}` | 200 `{user}`; signs in |
| `POST /auth/logout` | | 204 (session + CSRF) |
| `POST /auth/password-reset` | `{email}` | 202; a reset link if the account exists |
| `POST /auth/password-reset/confirm` | `{token, password}` | 204; every session is signed out |
| `GET /me` | | The user and their workspaces with roles |

Passwords are 12 to 128 characters and must not be a common password.

### Workspaces, members, invites and keys (session only)

| Method and path | Who | Result |
|---|---|---|
| `POST /workspaces` `{name}` | anyone signed in | 201; you're the owner |
| `PATCH /workspaces/{id}` `{name}` | admin | Renamed |
| `DELETE /workspaces/{id}` `{confirm_name}` | owner | 204; deletes everything in it |
| `POST /workspaces/{id}/transfer` `{user_id}` | owner | The member becomes owner; you become admin |
| `GET /workspaces/{id}/members` | admin | Members with roles |
| `PATCH /workspaces/{id}/members/{user_id}` `{role}` | admin | Role changed (below your own) |
| `DELETE /workspaces/{id}/members/{user_id}` | admin, or yourself | Removed, or you left |
| `POST /workspaces/{id}/invites` `{emails, role}` | admin | 1 to 20 invites, each emailed a 7-day link |
| `GET /workspaces/{id}/invites` | admin | Pending invites |
| `DELETE /workspaces/{id}/invites/{invite_id}` | admin | Revoked |
| `POST /invites/accept` `{token}` | the invited user, signed in | Joined, with the invite's role |
| `POST /workspaces/{id}/api-keys` `{name}` | admin | 201 with the key, shown once |
| `GET /workspaces/{id}/api-keys` | admin | Keys without secrets, with last use and revocation |
| `DELETE /workspaces/{id}/api-keys/{key_id}` | admin | Revoked immediately |

### Documents, search and answers (API key, or session + `X-Workspace-ID`)

| Method and path | Role | Result |
|---|---|---|
| `POST /documents` `{text, document_id?, title?, metadata?}` | editor | 201; re-using an id replaces the document |
| `POST /documents/upload` (multipart `file`, `document_id?`) | editor | 201; UTF-8 `.txt` or `.md`, file name as title |
| `GET /documents` | viewer | Documents with title, chunk count and metadata |
| `DELETE /documents/{document_id}` | editor | 204; gone from search and answers |
| `POST /search` `{query, top_k?, filters?}` | viewer | Chunks with cosine similarity scores; never calls the LLM |
| `POST /ask` `{question, top_k?, filters?}` | viewer | Answer with `[n]` citations and its sources |
| `POST /ask/stream` | viewer | The same answer as Server-Sent Events: `sources`, `token`..., `done` |
| `GET /health` | public | Status, database, chunk count, models |

**Filters** limit which chunks can match; a chunk must satisfy every filter given:

```json
{"query": "refund window", "filters": {"document_ids": ["refunds"], "metadata": {"source": "wiki"}}}
```

**Streaming** with curl needs `-N` so output isn't buffered. Errors before the first token return a normal status; an error after it arrives as `event: error`. Browsers can't use `EventSource` here (it only sends `GET`); read the response with `fetch` instead.

### Error statuses

| Status | When |
|---|---|
| 400 | Missing `X-Workspace-ID` on a session request, a cookie and a key together, a bad or expired email link, a malformed `Content-Length` |
| 401 | No credential, or an invalid, expired or revoked one; wrong email or password |
| 403 | Role too low, missing CSRF token, an API key on a session-only endpoint, an unverified email at sign-in |
| 404 | Unknown document, or a workspace or resource you don't belong to (never 403, so it doesn't confirm it exists) |
| 409 | Inviting an existing member; accepting an invite sent to another email |
| 410 | An invite that was used, revoked or has expired |
| 413 | Document longer than `MAX_DOCUMENT_CHARS`, or a request body over `MAX_REQUEST_BYTES` |
| 415 | Upload that isn't `.txt` or `.md` |
| 422 | Invalid input |
| 429 | Too many failed sign-ins, with `Retry-After` |
| 502 / 503 / 504 | The LLM provider rejected the request / is not configured, rate limited or overloaded, or the database is down / timed out |
| 500 | Unexpected error. Details go to the log, never to the client. |

## Configuration

Settings are environment variables, read from `.env` when present; real environment variables win. Invalid combinations stop the server at startup with a clear message.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible API) or `anthropic` |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | none, api.openai.com, `gpt-5-mini` | OpenAI-compatible provider |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | none, `claude-opus-5` | Claude |
| `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS` | `16000`, `120` | Answer length and provider timeout |
| `DATABASE_URL` | `...sourcely_app...@127.0.0.1:5434/sourcely` | What the API connects as: a role that owns no table |
| `MIGRATION_DATABASE_URL` | `...sourcely_owner...@127.0.0.1:5434/sourcely` | What Alembic connects as: the schema owner |
| `COOKIE_SECURE` | `true` | Send cookies only over HTTPS. `false` for plain-HTTP local work only. |
| `SESSION_IDLE_DAYS` | `14` | Sessions end after this long without use |
| `EMAIL_BACKEND`, `APP_BASE_URL` | `console`, `http://localhost:8000` | Emails go to the log; links in them start with this URL |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_QUERY_PREFIX` | bge-small, `384`, bge's instruction | The model, its vector size (checked at startup), and the prefix added to queries only |
| `EMBEDDING_CACHE_DIR` | `./data/models` | Where the model is downloaded |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | `800`, `120` | Chunk length and overlap, in characters |
| `MAX_DOCUMENT_CHARS`, `MAX_REQUEST_BYTES` | `200000`, `2097152` | Size limits |
| `DEFAULT_TOP_K`, `MIN_RELEVANCE` | `4`, `0.58` | Chunks retrieved, and the similarity a chunk needs to be used in an answer |
| `LOG_LEVEL` | `INFO` | Log verbosity |

`MIN_RELEVANCE` was calibrated on measured scores and checked again after moving to pgvector (identical scores). Rerun `uv run python -m scripts.calibrate` if you change the embedding model or prefix.

## Architecture

```
app/
  main.py             create_app(): components, middleware, routers, error handlers
  api/
    auth.py           Sessions and CSRF, API keys, the per-request Principal, IndexDep
    middleware.py     Request id and access log; request body size limit
    deps.py           Settings, embedder, store, database session, LLM
    routes/           health, auth, workspaces, members, api_keys, documents, search, ask
  core/               Settings, errors, logging, password hashing and tokens
  db/                 SQLAlchemy base, engine, tables
  schemas/            Pydantic request and response models
  services/           accounts, workspaces, invites, api_keys, email, chunking, embeddings,
                      ingestion, vector_store (pgvector), llm, rag
migrations/           Alembic revisions 0001 to 0006
docker/postgres/      init.sql: the two database roles and extensions
scripts/calibrate.py  Measures relevance scores to choose MIN_RELEVANCE
```

**How workspaces are kept apart,** three times over:

1. Each request resolves to one `Principal`: who, which workspace, which role.
2. Every store call takes that workspace, through a `WorkspaceIndex` that routes can't build without it.
3. PostgreSQL **row-level security** on `documents` and `chunks` shows only the workspace set on the current transaction. The API connects as `sourcely_app`, which owns no table, so it can't bypass the policy. Migrations run as `sourcely_owner`.

**How a question is answered:** the question is embedded with the same local model as the documents; pgvector returns the nearest chunks in the workspace by cosine similarity, within any filters; chunks below `MIN_RELEVANCE` are dropped, and if none are left the fixed answer is returned without an LLM call; otherwise the chunks go into the prompt as numbered `<source>` blocks, with instructions to use only them, cite them as `[n]`, and treat them as data rather than instructions.

The reasons behind each technology are in [`docs/TECH_STACK.md`](docs/TECH_STACK.md).

## Development

```bash
docker compose up -d db                               # the tests need Postgres
uv run pytest -q                                      # 412 tests; no network, no model downloads
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run mypy                                           # strict type checking
uv run pre-commit install                             # once: run the checks on every commit
```

The tests create a fresh database per run, migrate it, and drop it at the end. GitHub Actions runs the same checks against a Postgres service container on every push and pull request.

One test walks the route table and requires a cross-tenant case for every workspace data route, so a new route can't skip isolation testing.

| File | What's in it |
|---|---|
| [`SPEC.md`](SPEC.md) | API contract, configuration, decisions, success criteria and evidence |
| [`CLAUDE.md`](CLAUDE.md) | Conventions, commands and verified gotchas for working in this repo |
| [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) | Step-by-step record of how it was built, and why |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | Why each technology was chosen, with alternatives and limits |
| [`docs/INTERVIEW_PREP.md`](docs/INTERVIEW_PREP.md) | Questions about the design, with answers tied to the code |
| [`docs/product/`](docs/product/README.md) | The product plan: PRD, wireframes, flows, architecture, data flows |

## Known limits

- **No web interface yet.** Everything is API and curl.
- **Emails go to the log.** There's no real mail sender, so sign-up and invites need access to the server log.
- **No rate limits or quotas** beyond the sign-in throttle.
- **Text formats only.** Uploads accept `.txt` and `.md`, not PDF or DOCX.
- **No pagination** on `GET /documents`, and exact-match filters only.
- **The relevance threshold rests on a small sample** (22 questions). Recheck it on your own documents.
- **English-oriented embeddings** (bge-small-en).
- **Claude is untested live.**
- **Development credentials** in `docker/postgres/init.sql` and `docker-compose.yml`. Change them for anything shared.

## Next steps

The product plan in [`docs/product/`](docs/product/README.md) continues in phases:

- **Phase 2:** a web app (library, ask screen, search, members).
- **Phase 3:** PDF and DOCX with background processing, conversations with follow-up questions, answer feedback.
- **Phase 4:** usage insights, quotas and rate limits, an audit log.
