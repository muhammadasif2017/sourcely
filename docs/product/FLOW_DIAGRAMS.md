# Flow diagrams: Sourcely

These diagrams show what happens **inside the system** for each operation: which component calls which, in what order, and where errors branch off. The user-facing side of the same operations is in [`INTERACTION_FLOWS.md`](INTERACTION_FLOWS.md). Components are described in [`ARCHITECTURE.md`](ARCHITECTURE.md).

Each diagram is labelled **Built**, **Specced** or **Proposed**. Specced diagrams follow `SPEC.md` exactly. Where a Proposed step extends a Specced flow, the step is marked in the diagram.

| ID | Flow | Status |
|---|---|---|
| [FD-1](#fd-1-rag-pipeline-overview) | RAG pipeline overview | Built (ingest half), Specced (query half) |
| [FD-2](#fd-2-request-pipeline-and-workspace-resolution) | Request pipeline and workspace resolution | Built (middleware), Proposed (auth) |
| [FD-3](#fd-3-ingest-json-text) | Ingest JSON text, `POST /documents` | **Built** |
| [FD-4](#fd-4-upload-a-file-with-background-processing) | Upload a file with background processing | Proposed |
| [FD-5](#fd-5-ingestion-worker-and-job-states) | Ingestion worker and job states | Proposed |
| [FD-6](#fd-6-semantic-search) | Semantic search, `POST /search` | Specced |
| [FD-7](#fd-7-ask) | Ask, `POST /ask` | Specced |
| [FD-8](#fd-8-streamed-ask-with-follow-up-rewriting) | Streamed ask with follow-up rewriting | Specced, rewriting Proposed |
| [FD-9](#fd-9-sign-up-verify-and-sign-in) | Sign up, verify and sign in | Proposed |
| [FD-10](#fd-10-api-key-authentication) | API key authentication | Proposed |
| [FD-11](#fd-11-delete-a-document) | Delete a document | Specced, cascade Proposed |
| [FD-12](#fd-12-accept-an-invite) | Accept an invite | Proposed |
| [FD-13](#fd-13-rate-limit-and-quota-check) | Rate limit and quota check | Proposed |

---

## FD-1. RAG pipeline overview

The two halves of retrieval-augmented generation. Both halves must use the **same embedding model**, or query vectors and chunk vectors aren't comparable.

```mermaid
flowchart LR
    subgraph ingest["Ingest: once per document"]
        direction LR
        doc["Document<br/>text, md, pdf, docx"] --> extract["Extract text<br/>per page"]
        extract --> chunk["chunk_text<br/>800 chars, 120 overlap<br/>paragraph, line, sentence, word"]
        chunk --> embedD["embed_documents<br/>bge-small, 384 dims"]
        embedD --> store[("Vector store<br/>chunk text, vector,<br/>document id, page, tags")]
    end

    subgraph query["Query: once per question"]
        direction LR
        q["Question"] --> rewrite["Rewrite follow-up<br/>into standalone query<br/><i>Proposed</i>"]
        rewrite --> embedQ["embed_query<br/>same model"]
        embedQ --> knn["Nearest neighbours<br/>top_k, cosine, filters"]
        knn --> gate{"Any score at or above<br/>MIN_RELEVANCE?"}
        gate -- No --> refuse["Fixed answer:<br/>not enough information<br/>no LLM call"]
        gate -- Yes --> prompt["Prompt: system rules +<br/>numbered sources + question"]
        prompt --> llm["LLM"]
        llm --> answer["Answer with [n] citations<br/>+ the sources used"]
    end

    store -. searched by .-> knn
```

## FD-2. Request pipeline and workspace resolution

Every request passes through the same steps before a route runs. The middleware is **Built**. The auth step is **Proposed**.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant MW as RequestContextMiddleware
    participant A as auth.py (Proposed)
    participant DB as PostgreSQL
    participant R as Route handler
    participant S as Service

    C->>MW: HTTP request
    MW->>MW: Reuse valid X-Request-ID or generate one
    MW->>A: Resolve credential
    alt Authorization: Bearer sk_live_...
        A->>DB: Find API key by sha256(key), not revoked
        DB-->>A: workspace_id
        A->>A: Principal(api_key, workspace, role=editor)
    else Session cookie
        A->>DB: Find session by sha256(cookie), not expired
        DB-->>A: user_id
        A->>DB: Membership for (X-Workspace-ID, user_id)
        DB-->>A: role, or nothing
        A->>A: Principal(user, workspace, role)
    else No credential, or not found
        A-->>C: 401
    end
    opt Unsafe method with a session
        A->>A: X-CSRF-Token must match the CSRF cookie, else 403
    end
    A->>DB: SET LOCAL app.workspace_id (for row-level security)
    A->>R: Principal via PrincipalDep
    R->>R: Pydantic validation, else 422
    R->>R: Role check, else 403
    R->>S: Call with principal.workspace_id
    S-->>R: Result
    R-->>MW: Response
    MW->>MW: Add X-Request-ID, log one access line
    MW-->>C: Response
```

## FD-3. Ingest JSON text

`POST /documents`. **Built** (Task 3). Proposed additions for Phase 1 are only the auth step from FD-2 and the workspace id.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as documents.create_document
    participant CH as chunking.chunk_text
    participant E as FastEmbedEmbedder
    participant V as VectorStore

    C->>R: POST /documents {text, document_id?, title?, metadata?}
    R->>R: Pydantic: blank text, bad id, bad metadata keys or values give 422
    alt len(text) > MAX_DOCUMENT_CHARS
        R-->>C: 413 with the limit
    end
    R->>R: document_id = given id, or a new UUID
    R->>CH: chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    CH-->>R: chunks
    R->>E: embed_documents(chunks)
    Note over R,E: Embed first. If this fails,<br/>the old version is still intact.
    E-->>R: vectors
    R->>V: replace_document(id, chunks, vectors, metadata, title)
    V->>V: Delete every chunk with this document_id
    V->>V: Add chunks with ids "id:0", "id:1", ...
    R-->>C: 201 {document_id, title, chunks, characters}
```

## FD-4. Upload a file with background processing

`POST /documents/upload` for all file types, returning `202` (decision D8). **Proposed** for Phase 3.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant P as Caddy
    participant R as documents.upload
    participant L as limits.py
    participant FS as FileStore
    participant DB as PostgreSQL

    B->>P: POST /documents/upload (multipart: file, document_id?, tags?)
    P->>P: Body over 20 MB gives 413
    P->>R: Forward
    R->>R: FD-2 auth, Editor or above
    R->>R: Extension allowed and magic bytes match, else 415
    R->>L: Storage quota check
    alt Would exceed workspace storage
        L-->>B: 413 Workspace storage is full
    end
    R->>FS: Save file under workspaces/{ws}/{document_id}/v{n}
    FS-->>R: file_key
    R->>DB: BEGIN
    R->>DB: Upsert DOCUMENT (title from filename, tags)
    R->>DB: Insert DOCUMENT_VERSION n+1, status queued
    R->>DB: Insert INGESTION_JOB for that version
    R->>DB: COMMIT
    R-->>B: 202 {document_id, version, status: queued}
    Note over B: Library polls GET /documents<br/>every 3 s while anything is<br/>queued or processing
```

If saving the file succeeds but the transaction fails, the orphan file is removed by a daily cleanup that deletes files with no version row.

## FD-5. Ingestion worker and job states

**Proposed** for Phase 3. The worker is `python -m app.worker`, the same codebase as the API.

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker loop
    participant DB as PostgreSQL
    participant FS as FileStore
    participant X as extract.py
    participant CH as chunk_text
    participant E as Embedder

    loop Every 1 s while idle
        W->>DB: SELECT job FOR UPDATE SKIP LOCKED WHERE run_after <= now()
        DB-->>W: One job, or none
    end
    W->>DB: Version status processing, attempts + 1, locked_at = now()
    W->>FS: Read file
    W->>X: Extract text per page (txt, md, pdf, docx)
    alt No text, encrypted, corrupt, or too long
        X-->>W: ExtractionError(reason)
        W->>DB: Version failed with reason, delete job
    else Text extracted
        X-->>W: pages
        W->>CH: chunk each page, keep page numbers
        CH-->>W: chunks
        W->>E: embed_documents(chunks) in batches of 64
        E-->>W: vectors
        W->>DB: BEGIN
        W->>DB: Insert CHUNK rows with vectors for version n+1
        W->>DB: Version ready, DOCUMENT.live_version = n+1
        W->>DB: Delete CHUNK rows of the old version
        W->>DB: Delete job, insert event document_ready
        W->>DB: COMMIT
    end
    Note over W,DB: A crash before COMMIT leaves the job row.<br/>Its lock expires after 10 minutes and it runs again.<br/>After 3 attempts the version is marked failed.
```

**Version status**

```mermaid
stateDiagram-v2
    [*] --> queued: upload or replace accepted
    queued --> processing: worker locks the job
    processing --> ready: chunks committed, becomes live version
    processing --> queued: crash or timeout, attempts under 3, retry after backoff
    processing --> failed: extraction error, or third failed attempt
    failed --> queued: POST /documents/{id}/retry
    ready --> superseded: a newer version becomes ready
    superseded --> [*]: old chunks deleted in the same transaction
    ready --> [*]: document deleted
    failed --> [*]: document deleted
```

Backoff between attempts: 30 seconds, then 2 minutes.

## FD-6. Semantic search

`POST /search`. **Specced** (Task 4). The vector store is Chroma in the PoC and pgvector after D3. The route doesn't change.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as search route
    participant E as Embedder
    participant V as VectorStore

    C->>R: POST /search {query, top_k?, filters?}
    R->>R: query 1 to 2000 chars, top_k 1 to 20, filter limits, else 422
    R->>E: embed_query(query)
    E-->>R: query vector
    R->>V: query(vector, top_k, where = build_where(filters))
    Note over V: PoC: Chroma where with $in, $eq, $and<br/>Proposed: SQL WHERE workspace_id AND filters,<br/>ORDER BY cosine distance to the query vector
    V-->>R: chunks with cosine distance
    R->>R: score = 1 - distance, sort high to low
    R-->>C: 200 {query, results: [...]}, empty list if the store is empty
```

## FD-7. Ask

`POST /ask`. **Specced** (Task 5).

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as ask route
    participant RAG as rag.py
    participant E as Embedder
    participant V as VectorStore
    participant L as LLM adapter
    participant P as LLM provider

    C->>R: POST /ask {question, top_k?, filters?}
    R->>R: Validate, else 422
    R->>RAG: answer(question, top_k, filters)
    RAG->>E: embed_query(question)
    RAG->>V: query(vector, top_k, filters)
    V-->>RAG: hits with scores
    RAG->>RAG: Keep hits with score >= MIN_RELEVANCE
    alt No hits left
        RAG-->>R: Fixed "not enough information" answer, sources []
        R-->>C: 200, no LLM call made
    else Hits left
        alt LLM key missing
            RAG-->>C: 503 LLM provider not configured
        end
        RAG->>RAG: Build prompt: system rules, numbered source blocks, question
        RAG->>L: complete(system, user)
        L->>P: OpenAI-compatible chat.completions, or Anthropic beta.messages.create with fallbacks
        alt Success
            P-->>L: text
            L-->>RAG: answer
            RAG-->>R: answer, sources, provider, model
            R-->>C: 200 {answer, sources, provider, model}
        else Auth error, bad request, or refusal
            L-->>C: 502
        else Rate limited or overloaded
            L-->>C: 503
        else Timeout or connection error
            L-->>C: 504
        end
    end
```

The adapter turns every SDK exception into one `LLMError(status_code, detail)`, so the route maps errors in one place.

## FD-8. Streamed ask with follow-up rewriting

`POST /ask/stream`. The stream protocol is **Specced** (Task 9). The conversation steps (load history, rewrite, save messages) are **Proposed** for Phase 3 and marked `(P)`.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant R as ask_stream route
    participant CV as conversations.py (P)
    participant RAG as rag.py
    participant L as LLM adapter
    participant P as LLM provider
    participant DB as PostgreSQL (P)

    B->>R: POST /ask/stream {question, filters?, conversation_id?}
    R->>R: FD-2 auth, FD-13 limits, validation
    opt conversation_id given (P)
        R->>CV: Load last 6 turns and the saved scope
        CV->>L: Rewrite the follow-up into a standalone query
        alt Rewrite fails
            CV->>CV: Use the raw question and log a warning
        end
        CV-->>R: search_query
    end
    R->>RAG: Retrieve with search_query and filters
    alt No relevant hits
        R-->>B: 200 event sources {sources: []}
        R-->>B: event token {fixed "not enough information" text}
        R-->>B: event done
    else Relevant hits
        RAG->>L: stream(system, user)
        L->>P: Start streaming request
        Note over R,P: Wait for the first token before sending headers
        alt Error before the first token
            P-->>L: auth, rate limit, timeout...
            L-->>B: Normal HTTP status 502, 503 or 504
        else First token arrives
            R-->>B: 200 text/event-stream
            R-->>B: event sources {sources, provider, model, search_query (P)}
            R-->>B: event token {text}
            loop Each further delta, empty deltas skipped
                P-->>L: delta
                R-->>B: event token {text}
            end
            alt Provider stream ends normally
                R-->>B: event done
            else Error mid-stream
                R-->>B: event error {detail}, then close
            end
        end
    end
    opt conversation_id given (P)
        R->>DB: Save user message, assistant message, sources, outcome, timings
    end
    R->>DB: Insert answer event for usage insights (P)
```

If the browser disconnects (the user pressed Stop), the generator stops pulling from the provider, which closes the provider connection. The partial answer is saved with outcome `stopped`.

## FD-9. Sign up, verify and sign in

**Proposed** for Phase 1.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant R as auth routes
    participant DB as PostgreSQL
    participant M as Email service

    B->>R: POST /auth/signup {name, email, password}
    R->>R: Validate, common-password check, else 422
    R->>DB: Email already exists?
    alt New email
        R->>R: argon2id(password)
        R->>DB: Insert USER, unverified
        R->>R: token = 32 random bytes
        R->>DB: Store sha256(token), expires in 24 h
        R->>M: Send verify link with token
    else Existing email
        R->>M: Send "you already have an account" email
    end
    R-->>B: 202, the same response in both cases

    B->>R: POST /auth/verify {token}
    R->>DB: Find sha256(token), unused, not expired
    alt Valid
        R->>DB: Mark user verified, mark token used
        R->>DB: Create SESSION with sha256(session id)
        R-->>B: 200, Set-Cookie session and CSRF cookie
    else Invalid or expired
        R-->>B: 400 This link has expired
    end

    B->>R: POST /auth/login {email, password}
    R->>DB: Count recent failures for this email
    alt 5 or more in 15 minutes
        R-->>B: 429 with Retry-After
    end
    R->>DB: Load user by email
    R->>R: Verify argon2id hash, or hash a dummy value if no user (equal timing)
    alt Correct and verified
        R->>DB: New SESSION, new id on every sign-in
        R-->>B: 200, Set-Cookie
    else Wrong
        R->>DB: Record failure
        R-->>B: 401 Email or password is incorrect
    end
```

## FD-10. API key authentication

**Proposed** for Phase 1.

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin browser
    participant K as api_keys route
    participant DB as PostgreSQL
    participant I as Integrator tool
    participant R as Any data route

    A->>K: POST /api-keys {name} (session, Admin)
    K->>K: key = "sk_live_" + base62(32 random bytes)
    K->>DB: Insert API_KEY {prefix = first 12 chars, key_hash = sha256(key)}
    K-->>A: 201 {id, name, key}, the only time the full key is returned

    I->>R: POST /search, Authorization: Bearer key
    R->>DB: Look up sha256(key), revoked_at is null
    alt Found
        DB-->>R: workspace_id
        R->>R: Principal(api_key, workspace, editor)
        R->>DB: last_used_at = now(), at most once a minute
        R-->>I: 200
    else Not found or revoked
        R-->>I: 401
    end

    A->>K: DELETE /api-keys/{id}
    K->>DB: revoked_at = now()
    K-->>A: 204
```

A plain SHA-256 hash is enough for API keys (unlike passwords), because the key is 32 random bytes and can't be guessed.

## FD-11. Delete a document

`DELETE /documents/{document_id}`. The PoC behaviour (204, or 404 when unknown) is **Specced** (Task 7). The cascade across versions, files and sources is **Proposed**.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as documents.delete
    participant DB as PostgreSQL
    participant FS as FileStore

    C->>R: DELETE /documents/{id}
    R->>R: FD-2 auth, Editor or above
    R->>DB: BEGIN
    R->>DB: Find DOCUMENT (workspace_id, id)
    alt Not found, or in another workspace
        R-->>C: 404
    end
    R->>DB: Cancel queued jobs for its versions
    R->>DB: UPDATE message_source SET chunk_id = NULL for its chunks
    R->>DB: Delete CHUNK rows, DOCUMENT_VERSION rows, DOCUMENT row
    R->>DB: Insert event document_deleted
    R->>DB: COMMIT
    R->>FS: Delete files under workspaces/{ws}/{id}/
    Note over R,FS: After COMMIT, so a failed transaction never<br/>loses files. A failed file delete is retried<br/>by the daily orphan cleanup.
    R-->>C: 204
```

If the worker is processing a version of this document at the same moment, its final transaction finds the document gone and discards its chunks.

## FD-12. Accept an invite

**Proposed** for Phase 1 (API) and Phase 2 (UI).

```mermaid
sequenceDiagram
    autonumber
    participant Ad as Admin
    participant R as invites routes
    participant DB as PostgreSQL
    participant M as Email service
    participant U as Invitee browser

    Ad->>R: POST /workspaces/{ws}/invites {emails, role}
    R->>R: Role below the inviter's own, emails valid, not members
    R->>DB: Insert INVITE per email, sha256(token), expires in 7 days
    R->>M: Send invite links
    R-->>Ad: 201 pending invites

    U->>R: POST /invites/accept {token} with session
    R->>DB: Find invite by sha256(token)
    alt Missing, used or expired
        R-->>U: 410 Ask your admin for a new invite
    else Session email differs from the invite email
        R-->>U: 409 Sign in as the invited email
    else Valid
        R->>DB: BEGIN, insert MEMBERSHIP with role, mark invite accepted, COMMIT
        R-->>U: 200 {workspace_id}
    end
```

## FD-13. Rate limit and quota check

**Proposed** for Phase 4. Runs after auth, before the route's work.

```mermaid
flowchart TD
    req["Request with Principal"] --> rate{"Requests in the last 60 s for this<br/>user or key over the limit?"}
    rate -- Yes --> r429["429, Retry-After = seconds until<br/>the window has room"]
    rate -- No --> isAsk{"Route is /ask or /ask/stream?"}
    isAsk -- No --> isUp{"Route is an upload?"}
    isUp -- No --> go["Run route"]
    isUp -- Yes --> storage{"Storage used + file size<br/>over workspace limit?"}
    storage -- Yes --> s413["413 Workspace storage is full"]
    storage -- No --> go
    isAsk -- Yes --> retrieve["Retrieve first: FD-7 steps 3 to 5"]
    retrieve --> relevant{"Relevant hits?"}
    relevant -- No --> free["Not-enough-information answer,<br/>not counted against quota"]
    relevant -- Yes --> quota{"Questions today at or over<br/>the workspace daily limit?"}
    quota -- Yes --> q429["429, Retry-After = seconds<br/>until midnight UTC"]
    quota -- No --> count["Increment today's counter"] --> llm["Call the LLM"]
```

Counters live in a small Postgres table keyed by `(workspace_id, day)` for quotas, and a fixed-window counter per principal for rate limits. At pilot scale this avoids adding Redis (decision D5). If the API runs many copies with heavy traffic, the rate limiter moves to Redis.
