# Architecture: Sourcely

This document describes the system **as it is now** (verified against the code on 2026-09-18) and the **target** system that the [PRD](PRD.md) needs. Every component carries a status: **Built**, **Specced** or **Proposed** (see [README](README.md#status-labels-used-everywhere)).

Operation-by-operation sequences are in [`FLOW_DIAGRAMS.md`](FLOW_DIAGRAMS.md).

## Contents

1. [Current system (PoC)](#1-current-system-poc)
2. [Target system context](#2-target-system-context)
3. [Target containers](#3-target-containers)
4. [API components](#4-api-components)
5. [Data model](#5-data-model)
6. [API surface](#6-api-surface)
7. [Tenancy and security](#7-tenancy-and-security)
8. [Key decisions](#8-key-decisions)
9. [Deployment](#9-deployment)
10. [Observability](#10-observability)
11. [Scaling limits and next steps](#11-scaling-limits-and-next-steps)
12. [Migration path from the PoC](#12-migration-path-from-the-poc)

---

## 1. Current system (PoC)

One FastAPI process. Embeddings are computed in-process, and vectors live in an embedded ChromaDB on local disk. The LLM is an external API chosen in `.env`.

```mermaid
flowchart LR
    client["HTTP client<br/>curl, Swagger /docs"] --> mw

    subgraph api["FastAPI process: create_app()"]
        mw["RequestContextMiddleware<br/>X-Request-ID, access log<br/><b>Built</b>"] --> routes
        subgraph routes["Routes: thin"]
            health["GET /health<br/><b>Built</b>"]
            docs["POST /documents<br/><b>Built</b>"]
            docsMore["upload, list, delete<br/><b>Specced</b>"]
            search["POST /search<br/><b>Specced</b>"]
            ask["POST /ask, /ask/stream<br/><b>Specced</b>"]
        end
        routes --> deps["deps.py: SettingsDep,<br/>EmbedderDep, StoreDep<br/><b>Built</b>"]
        deps --> svc
        subgraph svc["Services"]
            chunk["chunking.py<br/><b>Built</b>"]
            emb["embeddings.py<br/>FastEmbedEmbedder<br/><b>Built</b>"]
            vs["vector_store.py<br/>count, replace_document<br/><b>Built</b>"]
            llm["llm.py<br/><b>Specced</b>"]
            rag["rag.py<br/><b>Specced</b>"]
        end
    end

    emb --> model[("bge-small-en-v1.5<br/>ONNX, ./data/models")]
    vs --> chroma[("ChromaDB PersistentClient<br/>./data/chroma")]
    llm --> provider["LLM provider<br/>Gemini, OpenAI, Claude, Ollama"]
```

**What's true of the PoC and stays true in the target:**

- Layered layout: routes validate and delegate, services hold logic, services never import from `app.api`.
- Components are built once in the lifespan hook and injected through `app.state` and `Depends()`, so tests swap in fakes.
- Route handlers are plain `def`, because fastembed, Chroma and the SDKs block. FastAPI runs them in its threadpool.
- `create_app()` factory with no module-level app.
- Re-ingest replaces a document, and embedding happens before the store is touched.
- The no-relevant-context path never calls the LLM.
- Streaming fetches the first token before sending headers, so early errors keep real HTTP statuses.

## 2. Target system context

```mermaid
flowchart TB
    asker(["Asker, Curator, Admin<br/>web browser"])
    integrator(["Integrator<br/>own tools"])
    sourcely["<b>Sourcely</b><br/>web app, API, worker"]
    llm["LLM provider<br/>OpenAI-compatible or Anthropic"]
    email["Email service<br/>SMTP or transactional API"]

    asker -- "HTTPS, session cookie" --> sourcely
    integrator -- "HTTPS, Bearer API key" --> sourcely
    sourcely -- "prompts with retrieved passages" --> llm
    sourcely -- "verification, reset, invites" --> email
```

Only two things leave the deployment: prompts to the LLM provider (question plus retrieved passages) and emails. Documents, embeddings and vectors stay on the deployment's own disks.

## 3. Target containers

```mermaid
flowchart LR
    browser(["Browser"]) --> proxy
    integ(["API client"]) --> proxy

    subgraph host["Docker Compose on one host"]
        proxy["Caddy<br/>TLS, routing<br/><b>Proposed</b>"]
        web["Web app<br/>Next.js, TypeScript<br/><b>Proposed</b>"]
        api["API<br/>FastAPI, create_app<br/><b>Built, extended</b>"]
        worker["Ingestion worker<br/>same codebase, own process<br/><b>Proposed</b>"]
        pg[("PostgreSQL + pgvector<br/>users, workspaces, documents,<br/>chunks and vectors, jobs,<br/>conversations, events<br/><b>Proposed</b>")]
        files[("File storage<br/>local volume or S3-compatible<br/><b>Proposed</b>")]
        models[("Model cache volume<br/>bge-small ONNX<br/><b>Built</b>")]
    end

    proxy -- "/app/*" --> web
    proxy -- "/documents, /search, /ask, /auth, /workspaces, ..." --> api
    web -- "fetch, same origin" --> proxy
    api --> pg
    api --> files
    api --> models
    worker --> pg
    worker --> files
    worker --> models
    api -- "LLM calls" --> ext["LLM provider"]
    api -- "emails" --> mail["Email service"]
```

| Container | Responsibility | Why it's separate |
|---|---|---|
| **Caddy** | TLS, one origin for web and API, request size limits | Same origin means first-party cookies and no CORS. Same pattern as `job-tracker`. |
| **Web app** | Screens in [`WIREFRAMES.md`](WIREFRAMES.md). Server components for pages, client components for Ask streaming. | UI work and releases independent of the API. |
| **API** | Every HTTP endpoint. Query embeddings, retrieval, LLM calls, streaming. Stateless, so it can run several copies. | Already exists. |
| **Worker** | Picks ingestion jobs, extracts text, chunks, embeds, writes vectors. | PDF extraction and batch embedding take seconds to minutes. They must not tie up API threads. |
| **PostgreSQL + pgvector** | All state, including vectors (decision [D3](#d3-vector-store-once-a-worker-exists)). | One system to back up, and deletes that remove rows and vectors in one transaction. |
| **File storage** | The original uploaded files, so documents can be re-processed when chunking or the model changes. | Files don't belong in the database. |

The API and worker are **one Python codebase** with two entry points: `uvicorn app.main:create_app --factory` and `python -m app.worker`. They share services, settings and the embedder.

## 4. API components

The layered layout stays. New modules are added inside the existing layers.

```mermaid
flowchart TB
    subgraph apiLayer["app/api"]
        mw2["middleware.py<br/>request id, access log<br/><b>Built</b>"]
        authDep["auth.py<br/>resolve session or API key<br/>to Principal and workspace<br/><b>Proposed</b>"]
        deps2["deps.py<br/>SettingsDep, EmbedderDep, StoreDep,<br/>LLMDep, PrincipalDep, DbDep<br/><b>Built, extended</b>"]
        r["routes/<br/>health, documents, search, ask <b>Built/Specced</b><br/>auth, workspaces, members, invites,<br/>api_keys, conversations, feedback, usage <b>Proposed</b>"]
    end
    subgraph svcLayer["app/services"]
        s1["chunking, embeddings <b>Built</b>"]
        s2["vector_store <b>Built</b>, becomes PgVectorStore <b>Proposed</b>"]
        s3["llm, rag <b>Specced</b>"]
        s4["extract.py: txt, md, pdf, docx <b>Proposed</b>"]
        s5["ingestion.py: enqueue, process job <b>Proposed</b>"]
        s6["accounts.py, workspaces.py, api_keys.py <b>Proposed</b>"]
        s7["conversations.py: history, query rewrite <b>Proposed</b>"]
        s8["limits.py: quotas, rate limits <b>Proposed</b>"]
        s9["storage.py: FileStore protocol,<br/>LocalFileStore, S3FileStore <b>Proposed</b>"]
    end
    subgraph dataLayer["app/db (Proposed)"]
        models2["models.py: SQLAlchemy 2 tables"]
        repo["repositories: every query takes workspace_id"]
        mig["alembic migrations"]
    end
    subgraph core["app/core"]
        c1["config, errors, logging <b>Built</b>"]
        c2["security.py: password hashing,<br/>token generation <b>Proposed</b>"]
    end
    worker2["app/worker.py<br/>job loop <b>Proposed</b>"]

    mw2 --> authDep --> deps2 --> r --> svcLayer
    svcLayer --> dataLayer
    worker2 --> s5
    svcLayer --> core
```

**Principal.** Every request resolves to one object:

```python
@dataclass(frozen=True)
class Principal:
    """Who is calling and in which workspace. Built once per request by app/api/auth.py."""

    user_id: UUID | None        # None for API keys
    api_key_id: UUID | None     # None for sessions
    workspace_id: UUID
    role: Role                  # owner, admin, editor, viewer. API keys are editor.
```

Routes receive it through `PrincipalDep` and pass `principal.workspace_id` to services. Services and repositories **require** a `workspace_id` argument, so an unscoped query can't be written by accident. Section 7 covers the second line of defence.

**How a browser request picks its workspace.** The web app sends `X-Workspace-ID` on every call. `auth.py` checks that the session's user is a member of that workspace and loads their role. An API key is bound to one workspace, so the header is not needed and is rejected if it disagrees.

## 5. Data model

```mermaid
erDiagram
    USER ||--o{ SESSION : has
    USER ||--o{ MEMBERSHIP : has
    WORKSPACE ||--o{ MEMBERSHIP : has
    WORKSPACE ||--o{ INVITE : has
    WORKSPACE ||--o{ API_KEY : has
    WORKSPACE ||--o{ DOCUMENT : has
    DOCUMENT ||--o{ DOCUMENT_VERSION : has
    DOCUMENT_VERSION ||--o{ CHUNK : has
    DOCUMENT_VERSION ||--o| INGESTION_JOB : "processed by"
    WORKSPACE ||--o{ CONVERSATION : has
    USER ||--o{ CONVERSATION : owns
    CONVERSATION ||--o{ MESSAGE : has
    MESSAGE ||--o{ MESSAGE_SOURCE : cites
    CHUNK |o--o{ MESSAGE_SOURCE : "cited by"
    MESSAGE ||--o{ FEEDBACK : receives
    WORKSPACE ||--o{ EVENT : logs

    USER {
        uuid id PK
        citext email UK
        text name
        text password_hash "argon2id"
        timestamptz email_verified_at
        timestamptz created_at
    }
    SESSION {
        bytea token_hash PK "sha256 of cookie value"
        uuid user_id FK
        timestamptz last_seen_at
        timestamptz expires_at
    }
    WORKSPACE {
        uuid id PK
        text name
        timestamptz created_at
    }
    MEMBERSHIP {
        uuid workspace_id PK
        uuid user_id PK
        text role "owner admin editor viewer"
        timestamptz created_at
    }
    INVITE {
        uuid id PK
        uuid workspace_id FK
        citext email
        text role
        bytea token_hash
        timestamptz expires_at
        timestamptz accepted_at
    }
    API_KEY {
        uuid id PK
        uuid workspace_id FK
        text name
        text prefix "first 12 chars"
        bytea key_hash
        timestamptz last_used_at
        timestamptz revoked_at
    }
    DOCUMENT {
        uuid workspace_id PK
        text document_id PK "PoC id rule"
        text title
        text_array tags "text[] with GIN index"
        jsonb metadata
        int live_version
        uuid created_by
        timestamptz updated_at
    }
    DOCUMENT_VERSION {
        uuid id PK
        uuid workspace_id FK
        text document_id FK
        int version
        text status "queued processing ready failed"
        text failure_reason
        text file_key "path in file storage"
        text mime_type
        int characters
    }
    CHUNK {
        uuid id PK
        uuid workspace_id FK
        uuid version_id FK
        int chunk_index
        int page
        text text
        vector embedding "384 dims"
    }
    INGESTION_JOB {
        uuid id PK
        uuid version_id FK
        int attempts
        timestamptz run_after
        timestamptz locked_at
        text last_error
    }
    CONVERSATION {
        uuid id PK
        uuid workspace_id FK
        uuid user_id FK
        text title
        jsonb scope "filters"
        timestamptz updated_at
    }
    MESSAGE {
        uuid id PK
        uuid conversation_id FK
        text role "user assistant"
        text content
        text search_query "rewritten question"
        text provider
        text model
        text outcome "answered no_context error"
        int latency_ms
    }
    MESSAGE_SOURCE {
        uuid message_id PK
        int position PK "the n in [n]"
        uuid chunk_id FK "null after delete"
        text document_title
        int page
        real score
    }
    FEEDBACK {
        uuid message_id PK
        uuid user_id PK
        text rating "up down"
        text reason
        text comment
    }
    EVENT {
        bigint id PK
        uuid workspace_id FK
        text type
        jsonb data
        timestamptz at
    }
```

**Notes on the model**

- **Document ids keep the PoC rule** and are unique per workspace, not globally. The primary key is `(workspace_id, document_id)`.
- **Versions make replace safe.** A new upload creates version `n+1`. Search reads only chunks of `live_version`. When `n+1` becomes Ready, `live_version` moves to it in one transaction, and the old chunks are deleted. A failed version never touches the live one.
- **Tags** are a `text[]` column with a GIN index. The PoC stored filters as Chroma metadata. In pgvector the filter becomes a SQL `WHERE`.
- **Chunks carry `workspace_id` directly**, not only through their version, so the vector query filters on it without a join and row-level security can check it.
- **`MESSAGE_SOURCE.chunk_id` becomes `NULL` when a document is deleted** (decision [D6](#d6-past-answers-when-a-cited-document-is-deleted)). The UI then shows "Source deleted" with the stored title.
- **Vector index:** HNSW with cosine distance on `chunk.embedding`. Similarity is `1 - distance`, which keeps the PoC `score` meaning and `MIN_RELEVANCE` calibration.

## 6. API surface

The PoC paths stay exactly as the client's brief fixed them. New endpoints are **additions**. None of them uses a `/v1` prefix, following `CLAUDE.md`.

| Method and path | Purpose | Auth | Status |
|---|---|---|---|
| `GET /health` | Liveness, index size, configured models | none | **Built** |
| `POST /documents` | Ingest JSON text, synchronous | Editor | **Built** (auth Proposed) |
| `POST /documents/upload` | Upload a file | Editor | **Built** for `.txt` and `.md` (201, synchronous). **Proposed** for PDF and DOCX (202, background), see [D8](#d8-upload-response-once-processing-is-in-the-background) |
| `GET /documents` | List documents | Viewer | **Built** (pagination, tags and status Proposed) |
| `GET /documents/{id}` | Document detail with versions | Viewer | **Proposed** |
| `GET /documents/{id}/chunks` | Chunks for the detail page | Viewer | **Proposed** |
| `PATCH /documents/{id}` | Edit title and tags | Editor | **Proposed** |
| `POST /documents/{id}/retry` | Re-queue a failed version | Editor | **Proposed** |
| `DELETE /documents/{id}` | Delete a document | Editor | **Built** |
| `POST /search` | Semantic search, with filters | Viewer | **Built** |
| `POST /ask` | Answer with sources, with filters | Viewer | **Built** (`conversation_id` Proposed) |
| `POST /ask/stream` | Streamed answer, SSE | Viewer | **Built** (`conversation_id` and `search_query` in the `sources` event Proposed) |
| `POST /auth/signup`, `/auth/verify`, `/auth/login`, `/auth/logout`, `/auth/password-reset`, `/auth/password-reset/confirm` | Accounts and sessions | none or session | **Built** (Phase 1) |
| `GET /me` | Current user and their workspaces | session | **Built** (Phase 1) |
| `POST /workspaces`, `PATCH /workspaces/{id}`, `DELETE /workspaces/{id}`, `POST /workspaces/{id}/transfer` | Workspace lifecycle | session, Owner or Admin | **Built** (Phase 1) |
| `GET /workspaces/{id}/members`, `PATCH/DELETE /workspaces/{id}/members/{user_id}` | Members and roles | Admin (or yourself, to leave) | **Built** (Phase 1) |
| `POST/GET /workspaces/{id}/invites`, `DELETE /workspaces/{id}/invites/{invite_id}`, `POST /invites/accept` | Invites | Admin, then invitee | **Built** (Phase 1) |
| `POST/GET /workspaces/{id}/api-keys`, `DELETE /workspaces/{id}/api-keys/{key_id}` | API keys (built under the workspace path) | Admin, session only | **Built** (Phase 1) |
| `GET /conversations`, `GET/PATCH/DELETE /conversations/{id}` | Conversations | owner of the conversation | **Proposed** |
| `PUT /messages/{id}/feedback`, `DELETE /messages/{id}/feedback` | Feedback | Viewer | **Proposed** |
| `GET /usage?period=30d` | Usage insights | Admin | **Proposed** |

**Credentials:** browser calls use the session cookie plus `X-Workspace-ID` and `X-CSRF-Token` on unsafe methods. API clients use `Authorization: Bearer sk_live_…`. The error table in SPEC gains three rows: `401` (no or bad credential), `403` (role too low), `429` (quota or rate limit, with `Retry-After`).

## 7. Tenancy and security

**Isolation has three layers.** A mistake in one is caught by the next.

| Layer | Mechanism |
|---|---|
| 1. Request | `auth.py` resolves exactly one workspace per request. No route reads a workspace id from the body. |
| 2. Code | Repository and vector-store functions take `workspace_id` as a required argument. A test walks every route with a foreign credential (the **X** tests in [`FEATURE_VALIDATION.md`](FEATURE_VALIDATION.md)). |
| 3. Database | PostgreSQL row-level security on every tenant table: `USING (workspace_id = current_setting('app.workspace_id')::uuid)`. The API sets it per transaction with `SET LOCAL`. The app's database role is not the table owner, so it can't bypass RLS. |

**Other controls**

| Threat | Control |
|---|---|
| Stolen session cookie | `HttpOnly`, `Secure`, `SameSite=Lax`. Server-side sessions that can be revoked. Rotate the session id on sign-in. |
| CSRF | `SameSite=Lax` plus a double-submit token on unsafe methods. |
| Password attacks | Argon2id. 5 failures per email per 15 minutes. Common-password check. |
| Leaked API key | Stored hashed, shown once, revocable, prefix visible for identification, scoped to one workspace with Editor rights and no management rights. |
| Malicious upload | Magic-byte type check, 20 MB limit at Caddy and in the API, uncompressed-size limit for DOCX, no macros executed, text extraction in the worker (not in the API process). |
| Prompt injection in documents | The system prompt treats context as data (SPEC). Sources are always shown, so manipulation is visible. Injection test set in CI. The LLM has no tools, so an injected instruction can't take actions. |
| Data sent to the LLM provider | Only the question, rewritten question, recent turns and retrieved passages. Production requires a paid provider with no-training terms. The free-tier warning from SPEC stays for development. |
| Secrets | `.env` and a secrets manager in production. Never in git. Never logged. |

## 8. Key decisions

Each decision is **Proposed** until the owner approves it. Approving one means amending `SPEC.md` first (the rule in `CLAUDE.md`).

### D1. Authentication: build or buy

- **Options:** own auth in FastAPI; a managed service (Clerk, Auth0, Supabase Auth).
- **Recommendation: own auth.** Sourcely must stay self-hostable with one `docker compose up`. A managed service adds an external dependency and a second user database. The needed scope (email and password, sessions, reset, invites) is small and well understood, and it's strong interview material.
- **Revisit when** enterprise SSO (SAML) is needed. Then a managed identity provider pays for itself.

### D2. Relational database

- **Recommendation: PostgreSQL** with SQLAlchemy 2 (typed ORM, works with mypy strict) and Alembic migrations. SQLite can't do row-level security, and it can't host the vector index in D3.

### D3. Vector store once a worker exists

The PoC uses embedded Chroma (`PersistentClient`). Once a separate worker process writes vectors while the API reads them, two processes share one embedded database, which Chroma doesn't support safely.

| Option | For | Against |
|---|---|---|
| Chroma server (client-server mode) | Smallest code change: `VectorStore` keeps its interface. | Another service to run and back up. Deletes aren't transactional with Postgres, so a crash can leave vectors for a deleted document. Tenant filtering is by metadata or one collection per workspace. |
| **pgvector in the same PostgreSQL** | One database, one backup. Document delete, version swap and vectors change in one transaction. Row-level security covers vectors too. SQL filters for tags and document ids. | Rewrites `vector_store.py`. Recall and speed need checking at larger sizes. |
| Qdrant | Fast, rich filtering. Already listed as a next step in SPEC. | Another service, and the same transactional gap as Chroma. |

- **Recommendation: pgvector.** Keep the `VectorStore` interface so routes don't change, and add a `PgVectorStore` behind it. Measure recall at top 4 against Chroma on the A3 test set before switching.
- **This is on the "ask first" list** in `CLAUDE.md` (switching the vector store).

### D4. Frontend stack

- **Recommendation: Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui.** It matches the owner's `job-tracker` project, so skills and components carry over. Ask streaming uses `fetch` with a `ReadableStream`, because the browser's `EventSource` supports only `GET` and `/ask/stream` is `POST`.
- Versions are pinned when Phase 2 starts, not here.

### D5. Background job runner

- **Options:** Postgres job table; Redis with RQ, arq or Celery.
- **Recommendation: a Postgres job table** polled with `SELECT … FOR UPDATE SKIP LOCKED`. No new service, jobs commit in the same transaction as the document version, and the volume (uploads, not requests) is low.
- **Revisit when** jobs exceed a few per second or scheduled jobs multiply.

### D6. Past answers when a cited document is deleted

- **Recommendation:** keep the answer text, set `message_source.chunk_id` to `NULL`, and show "Source deleted" with the stored title. The passage text itself is not kept, so deleting a document really removes its content.

### D7. Conversation visibility

- **Recommendation:** private to the creator. Sharing a conversation by link is a later feature.

### D8. Upload response once processing is in the background

SPEC's `POST /documents/upload` returns `201` after processing, synchronously. PDF and DOCX processing is too slow for that.

- **Recommendation:** in Phase 3, `POST /documents/upload` returns `202 Accepted` with `{document_id, status: "queued"}` for **every** file type, so clients handle one behaviour. The PoC has no external consumers yet, so the change is cheap now and expensive later. `POST /documents` (JSON text) stays synchronous `201`.

## 9. Deployment

| Environment | How | Notes |
|---|---|---|
| **Development** | `docker compose up` for Postgres; API, worker and web run locally with reload | Gemini free tier, the PoC setup |
| **Pilot** (Phases 2 and 3) | One VM, Docker Compose: Caddy, web, api, worker, postgres | Daily `pg_dump` to off-site storage, file volume backed up with it |
| **Later** | Managed Postgres, API and worker as separate services with 2 or more API copies, S3-compatible file storage | Only when metrics require it |

Configuration stays in environment variables through `Settings`. New settings: `DATABASE_URL`, `FILE_STORAGE` (`local` or `s3`) with its path or bucket, `SESSION_TTL_DAYS`, `EMAIL_*`, and the limit values from F12.

## 10. Observability

The PoC request-id logging stays. Added:

| Signal | What | Used for |
|---|---|---|
| Structured logs | JSON lines with `request_id`, `workspace_id`, `principal`, route, status, duration | Debugging a user's report from the request id shown in the UI |
| Answer events | One `event` row per ask: outcome, top score, number of sources, provider, model, time to first token, total time, token counts | F11 usage insights and the success metrics in the PRD |
| Job metrics | Queue length, job duration by file type, failures by reason | Ingestion health, the A2 and F4 targets |
| Health | `/health` adds database and worker heartbeat checks | Container health checks |

## 11. Scaling limits and next steps

| Limit | When it bites | Next step |
|---|---|---|
| One API process's threadpool (40 threads by default) | Many slow streaming answers at once | Run several API copies behind Caddy. The API is stateless. |
| Embedding on CPU in the worker | Large bulk uploads | More worker processes. `SKIP LOCKED` makes that safe. |
| pgvector HNSW memory | Around a few million chunks on one machine | Partition by workspace, or move vectors to Qdrant behind the same `VectorStore` interface. |
| Retrieval quality | A3 test set below target | Hybrid BM25 plus vector search (Postgres full-text search is already there), then a reranker. |

## 12. Migration path from the PoC

```mermaid
flowchart LR
    p0["<b>Phase 0</b><br/>Finish PoC Tasks 4 to 11<br/>Chroma, no auth"] --> p1a
    subgraph p1["Phase 1"]
        p1a["Add Postgres, Alembic,<br/>users, workspaces, sessions"] --> p1b["PrincipalDep on every route,<br/>workspace_id through services"]
        p1b --> p1c["PgVectorStore behind VectorStore,<br/>recall check vs Chroma"]
        p1c --> p1d["Import PoC Chroma data<br/>into a default workspace"]
        p1d --> p1e["API keys, RLS, X tests"]
    end
    p1e --> p2["<b>Phase 2</b><br/>Next.js web app"]
    p2 --> p3["<b>Phase 3</b><br/>Worker, PDF and DOCX,<br/>conversations, feedback"]
    p3 --> p4["<b>Phase 4</b><br/>Usage, quotas, audit"]
```

The PoC tests keep running at every step. Each route gains auth without changing its request or response body, so the existing integration tests only need a fixture that supplies a credential.
