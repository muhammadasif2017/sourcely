# Implementation Plan: Sourcely (proof of concept)

Source of truth: [`SPEC.md`](../SPEC.md). Tasks with acceptance criteria are in [`todo.md`](todo.md).

## Overview

This plan builds a FastAPI backend that runs the full RAG flow: document, then chunks, then local embeddings (fastembed), then ChromaDB, then semantic search, then retrieved context, then an LLM answer. The LLM is Gemini (free tier), OpenAI or Claude, chosen in `.env`. Extras: list and delete endpoints, metadata filters, streamed answers and Docker.

## Architecture decisions

- **Layered layout** (`api/`, `core/`, `schemas/`, `services/`), chosen by the user as standard practice. Routes stay thin and logic lives in services. See SPEC.md, Project structure.
- **App factory with injected components.** `create_app(settings, *, embedder=None, store=None, llm=None)` puts the embedder, store and LLM on `app.state`, and routes read them through `Depends()` getters in `app/api/deps.py`. Tests pass fakes in. Production builds the real components in the lifespan hook. There is no global state, so tests stay isolated.
- **Synchronous route handlers (`def`).** fastembed, Chroma and both SDK clients used here are blocking. FastAPI runs `def` handlers in its threadpool, so the event loop never blocks and no async wrappers are needed. The one exception is streaming, where a sync generator passed to `StreamingResponse` is also run in the threadpool.
- **Two small LLM classes, not a registry.** `OpenAICompatibleLLM` covers OpenAI, Gemini and Ollama through `base_url`. `AnthropicLLM` covers Claude. `create_llm(settings)` picks one with an `if`. Both translate SDK exceptions into a single `LLMError(status_code, detail)`, so routes map errors in one place.
- **Chunk ids are `{document_id}:{index}`, and re-ingest deletes before it adds.** Re-ingesting is idempotent, and a shorter new version leaves no orphan chunks behind.
- **Filters become a Chroma `where` clause in one pure function** (`build_where`). It can be unit-tested without Chroma.
- **Streaming gets its first token before it sends headers.** Configuration, auth, rate-limit and timeout errors therefore return real HTTP statuses. Only errors after the first token become an SSE `error` event.
- **Tests use a deterministic hashed bag-of-words embedder and an in-memory Chroma client** with a unique collection name per test, because ephemeral clients share state within a process. Tests make no network calls and download no models.

## Dependency graph

```
config ──┬── chunking
         ├── embeddings ─┐
         ├── store ──────┼── /documents ── /search ── /ask ──┬── /ask/stream
         └── llm ────────┘        │            │             │
                              upload, list/delete   filters ─┘
                                                        └── Docker, README
```

## Task list

### Phase 1: Foundation
- [x] Task 1: Skeleton, configuration, `/health` and standard tooling (layered layout, request ids, mypy, pre-commit, CI)
- [x] Task 2: Chunking

### Checkpoint A: foundation
- [x] `pytest` and `ruff` are clean, and the server boots to show `/health` and `/docs`

### Phase 2: Core RAG flow (vertical slices)
- [x] Task 3: Ingest slice, `POST /documents`
- [x] Task 4: Search slice, `POST /search`
- [x] Task 5: Ask slice, `POST /ask` with Gemini, OpenAI and Claude providers

### Checkpoint B: live end-to-end check (human review)
- [x] Real fastembed model and Gemini: ingest, then search, then ask all work. The "no information" path makes no LLM call. `MIN_RELEVANCE` is calibrated and recorded in `SPEC.md`.

### Phase 3: Extras
- [x] Task 6: `POST /documents/upload`
- [x] Task 7: `GET /documents` and `DELETE /documents/{id}`
- [x] Task 8: Metadata and document filters on `/search` and `/ask`
- [x] Task 9: `POST /ask/stream` (SSE)

### Checkpoint C: extras
- [x] All tests pass. A live `curl -N` stream on Gemini shows tokens arriving progressively. Delete removes the document from list and search.

### Phase 4: Ship
- [x] Task 10: Docker
- [x] Task 11: README and final verification against the spec's success criteria

### Checkpoint D: complete
- [x] Every success criterion in `SPEC.md` has evidence. Approved by the owner on 2026-09-19.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| The first run downloads the bge-small model (about 130 MB), which is slow or fails behind a proxy | Medium | Download once during Checkpoint B. Put the cache directory in settings so Docker can mount a volume for it. Document it in the README. |
| Gemini free tier returns 429, or a model is retired (`gemini-2.5-*` already returns 404 for new users) | Medium | Keep live checks to about 10 requests total. Map 429 to 503 with a clear detail. Pin the model in `.env` so it's a one-line change. |
| Gemini's OpenAI-compatible endpoint differs from OpenAI in streaming or `max_completion_tokens` handling | Medium | Verify streaming live in Task 9 before calling it done. Guard against chunks with empty `choices` or a `None` delta. |
| The Claude path cannot be tested live, since there is no key | Medium | Write it against the installed SDK signatures (already checked: `fallbacks`, `betas`, `stream`). Unit-test the call shape and error mapping with a fake client. Say so plainly in the README. |
| The bge-small scores for unrelated text sit high (about 0.4 to 0.5), so a wrong `MIN_RELEVANCE` either blocks good answers or lets noise through | Medium | Measure related and unrelated scores on a real corpus at Checkpoint B, pick the threshold from that data, and record the numbers. |
| Chroma locks files on Windows, which breaks cleanup of temporary directories in tests | Low | Tests use `EphemeralClient` (in memory), never `PersistentClient`. |
| The Docker image is large because of onnxruntime | Low | Use a `python:3.12-slim` base with `uv sync --frozen --no-dev`, and keep the model cache in a volume rather than the image. |

## Parallelization

The work is sequential. It's one agent on one codebase, and each slice extends the one before. Tasks 6, 7 and 8 are independent of each other after Task 5, but they're too small to be worth splitting across agents.

## Open questions

- None blocking. `MIN_RELEVANCE` is resolved with data at Checkpoint B.

## Phase 5: Product Phase 1 (accounts, workspaces, API keys)

Approved 2026-09-19 with decisions D1 (own auth), D2 (PostgreSQL) and D3 (pgvector). The contract is in `SPEC.md`, section "Phase 1"; tasks are in `todo.md`.

### Architecture decisions

- **Order: data foundation, then identity, then tenancy, then vectors.** Postgres and migrations (12), accounts (13), workspaces and the `Principal` (14) and API keys (15) come before the vector store moves (16). API keys come before Task 16 so the test client can authenticate with one header, which keeps the 233 PoC tests unchanged.
- **Two database roles.** Migrations run as the owner; the app connects as a role that owns nothing, so row-level security can't be bypassed by accident.
- **Row-level security on tenant content only** (`documents`, `chunks`). Tables used to resolve identity are protected in code, because they're read before the workspace is known.
- **Sync SQLAlchemy.** Matches the existing `def` routes and threadpool model; no async rewrite.
- **Generated cross-tenant tests.** One test walks the route table, so new routes can't skip isolation checks.

### Tasks

- [x] Task 12: Postgres foundation
- [x] Task 13: Accounts and sessions
- [x] Task 14: Workspaces, roles and the Principal
- [x] Task 15: API keys
- [x] Task 16: Tenant data on pgvector

### Checkpoint E: isolation (human review)
- [ ] Isolation proven at the HTTP and database levels; parity gate passed.

- [ ] Task 17: Members and invites
- [ ] Task 18: Compose, docs and live verification

### Checkpoint F: Phase 1 complete
- [ ] Every Phase 1 success criterion in `SPEC.md` has evidence.

### Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Tests now need Postgres, so the suite is slower and fails without Docker | Medium | One database per run with truncation between tests; a clear error when the database isn't reachable; CI service container |
| pgvector scores differ from Chroma and `MIN_RELEVANCE` stops fitting | Medium | Parity gate with `scripts/calibrate.py` before Chroma is removed |
| Row-level security silently bypassed because the app connects as the table owner | High | Two roles from the first migration, and a database-level test that would fail if RLS were bypassed |
| An endpoint forgets workspace scoping | High | `workspace_id` required in every tenant function, RLS underneath, and generated cross-tenant tests |
| Auth mistakes: timing leaks, CSRF gaps, token reuse | High | Spec rules turned into tests: identical responses, dummy hash, CSRF on every session write, single-use hashed tokens |
