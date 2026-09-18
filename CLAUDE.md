# CLAUDE.md

Operational guidance for working in this repository: commands, conventions, boundaries and verified gotchas. The *why* lives elsewhere:

- `SPEC.md`: the source of truth for the API contract, configuration and success criteria. Read only the section relevant to the task.
- `tasks/plan.md` and `tasks/todo.md`: architecture decisions and task status. Check `todo.md` to see what's next.
- `docs/TECH_STACK.md`: why each technology was chosen.
- `docs/BUILD_LOG.md` and `docs/INTERVIEW_PREP.md`: learning docs for the owner, who is new to FastAPI.

## Commands

```bash
uv sync                                                  # install from uv.lock
uv run uvicorn app.main:create_app --factory --reload    # dev server, http://localhost:8000/docs
uv run pytest -q                                         # tests (no network, no model downloads)
uv run ruff check . && uv run ruff format --check .      # lint and format
uv run mypy                                              # strict type check of app/
uv run pre-commit run --all-files                        # every hook, the same checks as CI
```

**Always use `--factory`.** There is intentionally no module-level `app` in `app/main.py`, so importing it never reads `.env` or loads models. `uvicorn app.main:app` will fail.

To stop a server on Windows, kill it by port: `Get-NetTCPConnection -LocalPort 8000 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`.

## Project map

```
app/main.py              create_app(): lifespan builds the embedder and store unless injected; wires middleware, handlers, routers
app/api/deps.py          Depends() getters reading app.state, plus *Dep Annotated aliases
app/api/middleware.py    Raw-ASGI X-Request-ID and access log (raw so streaming passes through)
app/api/routes/          One APIRouter per resource
app/core/                config.py (Settings), errors.py (AppError and handlers), logging.py
app/schemas/             Pydantic request and response models, one module per resource
app/services/            Business logic. Never imports from app.api.
tests/conftest.py        FakeEmbedder, in-memory store, settings and client fixtures
tests/unit/, tests/integration/
```

## Conventions

- **Layering:** routes stay thin. They validate, call a service and return a schema. Logic lives in `app/services/`.
- **Route handlers are plain `def`, not `async def`.** fastembed, Chroma and the SDK clients as used here are blocking. FastAPI runs `def` handlers in its threadpool.
- **Components reach routes only through `app/api/deps.py`:** `SettingsDep`, `EmbedderDep`, `StoreDep`, and `LLMDep` once Task 5 lands. Never read `app.state` in a route directly.
- **Every route declares `response_model`** and a non-default `status_code` where the spec says so. Errors are raised as `AppError(status, safe_detail)`.
- **Docstring on every public module, class and function.** Inline comments explain *why*, not *what*.
- **Typing:** mypy strict passes. Library calls that return `Any` (fastembed's `.tolist()`, chromadb results) go into an explicitly typed variable before `return`.
- **Loggers:** `logging.getLogger(__name__)`, so everything is under `app.*`. `configure_logging` sets `propagate=False` on `app`.
- **Pattern to copy for a new route:**

```python
router = APIRouter(tags=["search"])

@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, embedder: EmbedderDep, store: StoreDep) -> SearchResponse:
    """One-line summary shown in /docs."""
    ...
```

## Workflow

- Work task by task from `tasks/todo.md`: write tests first, then implement, then run pytest, ruff and mypy. Stop at each checkpoint for owner review.
- At the end of every task, update `docs/BUILD_LOG.md` and `docs/INTERVIEW_PREP.md`. Add any new dependency to `docs/TECH_STACK.md`. Tick the boxes in `tasks/todo.md` and `tasks/plan.md`.
- **Commit once per task, after all checks pass.** Messages are short, single-line and descriptive, with no attribution lines. pre-commit runs ruff, mypy and hygiene hooks and blocks the commit on failure. Fix the cause; never use `--no-verify`.
- If code and `SPEC.md` disagree, stop and ask. Update the spec first when a decision changes.

## Boundaries

- **Never:** commit `.env` or anything under `data/`, put real keys in `.env.example`, call paid or network APIs from tests, or return stack traces to clients.
- **Ask first:** new dependencies beyond `SPEC.md`'s tech stack, switching the vector store, auth, or changing the public API paths. Paths are fixed by the client's brief: `/documents`, `/search`, `/ask`. Don't add a `/v1` prefix.

## Verified gotchas

- **Python 3.12 is pinned.** The system Python is 3.14, where onnxruntime wheels are unreliable. Don't change `.python-version`.
- **Chroma `EphemeralClient` instances share one in-process database.** Every test needs its own collection name (`conftest.py` uses `test-<uuid>`). Collection names must be 3 to 512 characters from `[a-zA-Z0-9._-]`.
- **Always create collections with `embedding_function=None`.** We pass our own vectors, and otherwise Chroma downloads its default model. Collections use cosine space, so similarity = `1 - distance`.
- **fastembed `query_embed()` returns the same vector as `embed()` for bge-small-en-v1.5.** Verified: it adds no query instruction. Don't claim otherwise.
- **The model downloads to `EMBEDDING_CACHE_DIR` (`./data/models`, about 65 MB) on first start.** fastembed's default cache is a temp directory that the OS can wipe.
- **Gemini:** `gemini-2.5-*` models return 404 for new users. `gemini-3.5-flash-lite` is verified and pinned. On the free tier, Google may use the data, so don't ingest confidential text. Live checks spend free quota; keep them to a handful of requests.
- **Anthropic SDK 1.6** is built on `httpx2`. Never pass `httpx` objects to it. For Claude, use `client.beta.messages.create/stream(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`, with model `claude-opus-5`. Check `stop_reason == "refusal"` before reading content. This path can't be tested live (no key), so it's unit-tested with fakes.
- **OpenAI SDK 3.x:** use `max_completion_tokens`. The same client serves Gemini and Ollama through `OPENAI_BASE_URL`.
- **pre-commit excludes `uv.lock` from `check-added-large-files`.** Lockfiles belong in git.
- **`TestClient(app, raise_server_exceptions=False)`** is needed to assert on the generic 500 response.
