# Build Log: how this project was built, step by step

This log records every step taken to build Sourcely, a RAG API, in order, with the commands that were run and the reasons behind them. It is written for someone who is new to FastAPI. Each step explains the framework or Python concept it relies on, so you can rebuild the project yourself and explain it in an interview.

- **What** we are building and the decisions that shape it: [`SPEC.md`](../SPEC.md)
- **The task order** and progress: [`tasks/plan.md`](../tasks/plan.md), [`tasks/todo.md`](../tasks/todo.md)
- **Why each technology was chosen** (problem solved, advantages, alternatives, limitations): [`TECH_STACK.md`](TECH_STACK.md)
- **Interview questions** about this project: [`INTERVIEW_PREP.md`](INTERVIEW_PREP.md)

The log is updated at the end of every task.

---

## Contents

1. [Step 0: Check the environment](#step-0-check-the-environment)
2. [Step 1: Create the project with uv](#step-1-create-the-project-with-uv)
3. [Step 2: Decide before coding](#step-2-decide-before-coding)
4. [Step 3: Write the spec and the plan](#step-3-write-the-spec-and-the-plan)
5. [Step 4 (Task 1): Skeleton, settings, health check and tooling](#step-4-task-1-skeleton-settings-health-check-and-tooling)
6. [Step 5 (Task 2): Chunking](#step-5-task-2-chunking)
7. [Step 6 (Task 3): Ingesting documents, `POST /documents`](#step-6-task-3-ingesting-documents-post-documents)
8. [Step 7: Product planning (after Task 3)](#step-7-product-planning-after-task-3)
9. [Step 8 (Task 4): Semantic search, `POST /search`](#step-8-task-4-semantic-search-post-search)
10. [Step 9 (Task 5): Answering questions, `POST /ask`](#step-9-task-5-answering-questions-post-ask)
11. [Step 10: Checkpoint B, live check and calibration](#step-10-checkpoint-b-live-check-and-calibration)
12. [Step 11 (Task 6): File upload, `POST /documents/upload`](#step-11-task-6-file-upload-post-documentsupload)
13. [Step 12 (Task 7): Listing and deleting documents](#step-12-task-7-listing-and-deleting-documents)
14. [Step 13 (Task 8): Filters on `/search` and `/ask`](#step-13-task-8-filters-on-search-and-ask)
15. [Step 14 (Task 9): Streaming answers, `POST /ask/stream`](#step-14-task-9-streaming-answers-post-askstream)
16. [Step 15 (Task 10): Docker, and a request size limit](#step-15-task-10-docker-and-a-request-size-limit)
17. [Step 16 (Task 11): README and final verification](#step-16-task-11-readme-and-final-verification)
18. [Step 17 (Task 12): Postgres foundation](#step-17-task-12-postgres-foundation)
19. [Step 18 (Task 13): Accounts and sessions](#step-18-task-13-accounts-and-sessions)
20. [Step 19 (Task 14): Workspaces, roles and the Principal](#step-19-task-14-workspaces-roles-and-the-principal)
21. [Step 20 (Task 15): API keys](#step-20-task-15-api-keys)
22. [Step 21 (Task 16): Tenant data on pgvector](#step-21-task-16-tenant-data-on-pgvector)
23. [How to run everything built so far](#how-to-run-everything-built-so-far)
24. [Glossary](#glossary)

---

## Step 0: Check the environment

Before creating anything, we checked which tools the machine has:

```bash
python --version        # Python 3.14.2
uv --version            # uv 0.9.22
uv python list          # shows 3.12 and 3.13 are also installed
```

**Why this matters.** Two of our libraries, `chromadb` and `fastembed`, depend on `onnxruntime`, a compiled C++ library. Compiled libraries ship pre-built "wheels" for each Python version, and brand-new Python versions (3.14 here) often don't have wheels yet. Python 3.12 is mature and fully supported, so we pinned the project to it. The system Python stays untouched.

We also checked the neighbouring projects in `C:\dev` (`helpdesk-copilot`, `job-match-service`) so this one follows the same conventions: `uv`, `pydantic-settings`, `ruff`, `pytest`, and a `.python-version` file.

## Step 1: Create the project with uv

[uv](https://docs.astral.sh/uv/) is a fast Python package and project manager. It replaces `pip`, `venv` and `pip-tools` with one tool.

```bash
cd C:\dev
uv init --app --no-readme rag-api     # creates pyproject.toml, .python-version, .gitignore, git repo
cd rag-api
```

The project started as `rag-api` and was renamed to Sourcely after Task 3, because every answer comes with its sources. The folder is now `sourcely`.

```bash
uv python pin 3.12                    # writes "3.12" into .python-version
uv add fastapi "uvicorn[standard]" chromadb fastembed pydantic-settings anthropic openai
uv add --dev pytest httpx ruff mypy pre-commit
```

`uv init` initially wrote `requires-python = ">=3.13"`, which conflicts with pinning 3.12, so we edited it to `>=3.12` in `pyproject.toml`.

What each file is for:

| File | Purpose |
|---|---|
| `pyproject.toml` | The project's manifest: name, Python version, dependencies, and settings for tools (ruff, mypy, pytest). This is the modern standard (PEP 621) that replaces `setup.py` and `requirements.txt`. |
| `uv.lock` | The exact version of every package, including sub-dependencies. It makes installs reproducible: anyone who runs `uv sync` gets identical versions. Commit it. |
| `.python-version` | Tells uv which Python to use for this folder. |
| `.venv/` | The virtual environment: an isolated folder of installed packages for this project only. Never commit it. |

What each dependency does:

| Package | Role |
|---|---|
| `fastapi` | The web framework. You write Python functions, and it turns them into HTTP endpoints with validation and automatic docs. |
| `uvicorn[standard]` | The ASGI server that actually listens on a port and runs the FastAPI app. `[standard]` adds faster optional extras. |
| `pydantic-settings` | Loads configuration from environment variables and `.env` into a typed class. |
| `chromadb` | The vector database. It stores embeddings and finds the nearest ones. |
| `fastembed` | Runs the embedding model locally on CPU (ONNX), with no API key. |
| `openai`, `anthropic` | Official SDKs for calling LLMs. The `openai` SDK also talks to Gemini and Ollama through their OpenAI-compatible endpoints. |
| `pytest`, `httpx` | Testing. FastAPI's `TestClient` is built on `httpx`. |
| `ruff`, `mypy`, `pre-commit` | Lint and format, static type checking, and automatic checks before each commit. |

**`--dev` dependencies** are only needed while developing, not in production. They are excluded from the Docker image later.

## Step 2: Decide before coding

These decisions were made with the user before any code was written (see `SPEC.md`, Decisions):

1. **Vector store: Chroma, embedded mode.** Chroma runs inside our Python process and saves to a folder (`data/chroma`), like SQLite does. It needs no server, no Docker and no API key. Qdrant was the alternative; it's better at large scale but needs more setup.
2. **Embeddings: local fastembed with `BAAI/bge-small-en-v1.5`.** Claude has no embeddings API, and the user has no paid keys. fastembed runs a small (384-dimension) model on the CPU for free.
3. **LLM: switchable in `.env`.** The task said "OpenAI or Claude", so both are supported. The user has no paid credit, so development uses Google Gemini's free tier through Google's OpenAI-compatible endpoint. That's the same `openai` SDK code, just with a different `base_url`.
4. **We verified the Gemini model names live before writing them down.** `gemini-2.5-flash-lite` now returns 404 for new users, and `gemini-3.5-flash-lite` works. Verifying against the real service beat trusting memory.

## Step 3: Write the spec and the plan

We followed a **spec-driven** workflow: write down *what* and *why* before *how*.

- `SPEC.md` holds the objective, the API contract (every endpoint, request, response and error code), configuration, project structure, testing strategy, boundaries and success criteria.
- `tasks/plan.md` holds the architecture decisions, the dependency graph and the risks.
- `tasks/todo.md` breaks the work into 11 small tasks, each with acceptance criteria and a way to verify it, plus checkpoints for human review.

**Why bother?** The spec surfaced several decisions that would otherwise have been guessed silently: what happens when a document is re-uploaded, what `/ask` does when nothing relevant is found, and which HTTP status each failure returns. Changing a document costs minutes. Changing code after a wrong guess costs hours.

---

## Step 4 (Task 1): Skeleton, settings, health check and tooling

Commit: `d64e5b0`, "Add app skeleton, config, health endpoint and dev tooling".

### 4.1 Project layout

```
app/
  main.py              create_app(): builds and wires the FastAPI application
  api/
    deps.py            Dependency functions that give routes their components
    middleware.py      Request id and access log for every request
    routes/health.py   The GET /health endpoint
  core/
    config.py          Settings loaded from .env
    errors.py          AppError and exception handlers
    logging.py         Log format that includes the request id
  schemas/health.py    Pydantic model describing the /health response
  services/
    embeddings.py      Turns text into vectors (fastembed)
    vector_store.py    Wraps the Chroma collection
tests/
  conftest.py          Shared test fixtures and fakes
  unit/                Tests of single functions or classes
  integration/         Tests that go through HTTP with TestClient
```

**Why layers?** Each folder has one job, and dependencies point one way: `api` uses `services` and `schemas`, and `services` never import from `api`.

- **`api/`** is the HTTP layer: routes, request parsing and dependencies. It should be thin.
- **`services/`** holds the business logic (chunking, embedding, search, LLM calls). It knows nothing about HTTP, so it can be tested and reused without a web server.
- **`schemas/`** holds the data shapes that go in and out of the API.
- **`core/`** holds cross-cutting things every layer needs: configuration, errors and logging.

This is the structure FastAPI's documentation calls ["Bigger Applications"](https://fastapi.tiangolo.com/tutorial/bigger-applications/). Most production FastAPI codebases use some version of it.

Every folder has an empty `__init__.py`. That file marks the folder as a Python **package**, so `from app.core.config import Settings` works.

### 4.2 Settings with pydantic-settings (`app/core/config.py`)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = None
    chunk_size: int = Field(800, ge=50)
    ...
```

How it works:
- Each attribute maps to an environment variable with the same name, case-insensitive. `chunk_size` reads `CHUNK_SIZE`.
- Values come from, in priority order: real environment variables, then the `.env` file, then the default in the class.
- Pydantic **converts and validates** the values. `CHUNK_SIZE=abc` fails, and so does `LLM_PROVIDER=cohere` (not in the `Literal`).
- `Field(800, ge=50)` means the default is 800 and the value must be at least 50.
- A `@model_validator` checks rules that involve several fields together, such as `chunk_overlap < chunk_size`.
- `@property` methods such as `llm_configured` compute values from other fields.

`get_settings()` is wrapped in `@lru_cache`, so the `.env` file is read once and every caller gets the same object.

**Why not `os.getenv()` everywhere?** Scattered `getenv` calls give you strings with no validation, typos fail silently, and nothing documents what configuration exists. A settings class gives you one typed, validated, self-documenting source of truth that fails fast at startup.

`.env` holds real secrets and is in `.gitignore`. `.env.example` is committed as a template with placeholder values.

### 4.3 The app factory and lifespan (`app/main.py`)

```python
def create_app(settings=None, *, embedder=None, store=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.embedder = embedder or FastEmbedEmbedder(...)
        app.state.store = store or VectorStore(chromadb.PersistentClient(...), ...)
        yield            # the app serves requests while paused here

    app = FastAPI(title="Sourcely", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app
```

Key ideas:

- **App factory.** Instead of creating `app = FastAPI()` at the top of the file, a function builds it. Tests can then build a fresh app with fake components each time. The server starts it with `uvicorn app.main:create_app --factory`, where `--factory` tells uvicorn to call the function to get the app.
- **Why no module-level `app`?** With one at module level, merely *importing* `app.main` (which tests do) would read `.env` and try to load the embedding model. A broken local `.env` would then crash the test run before any test started.
- **Lifespan.** Code before `yield` runs once at startup; code after it runs once at shutdown. It's the right place for expensive setup such as loading the 65 MB embedding model once instead of per request. It replaces the older `@app.on_event("startup")`.
- **`app.state`** is a place to store shared objects on the application. Routes reach them through dependencies (next section).
- **Injection:** if a test passes `embedder=FakeEmbedder()`, the lifespan uses it instead of loading the real model.

### 4.4 Routers (`app/api/routes/health.py`)

```python
router = APIRouter(tags=["health"])

@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep, embedder: EmbedderDep, store: StoreDep) -> HealthResponse:
    ...
```

An `APIRouter` groups related endpoints in their own file. `main.py` attaches it with `app.include_router(health.router)`. `tags` groups the endpoints in the `/docs` page.

**`def` vs `async def`.** This handler is a plain `def`. FastAPI runs plain `def` handlers in a thread pool, so blocking work doesn't freeze the server. Our libraries (Chroma, fastembed, the SDK clients as used here) are blocking, so `def` is the correct choice. Use `async def` only when everything inside is awaited and non-blocking. A blocking call inside `async def` stalls every other request.

### 4.5 Dependency injection (`app/api/deps.py`)

```python
def get_store(request: Request) -> VectorStore:
    return request.app.state.store

StoreDep = Annotated[VectorStore, Depends(get_store)]
```

When a route declares a parameter of type `StoreDep`, FastAPI calls `get_store(request)` and passes the result in. This is FastAPI's **dependency injection** system.

- Routes don't know *where* components come from, so they're easy to test and change.
- `Annotated[Type, Depends(fn)]` stored in an alias (`StoreDep`) is the modern, recommended style. It avoids repeating `= Depends(get_store)` in every route.
- Tests can also replace a dependency with `app.dependency_overrides[get_store] = ...`. We don't need that, because we inject fakes through `create_app`.

### 4.6 Response models (`app/schemas/health.py`)

```python
class HealthResponse(BaseModel):
    status: str
    chunks_indexed: int
    ...
```

A Pydantic `BaseModel` declares the exact shape of the response. `response_model=HealthResponse` on the route means FastAPI validates the output, filters out any extra fields (so nothing leaks by accident), and documents the shape in OpenAPI. Open `http://localhost:8000/docs` to see the interactive Swagger UI generated from these models.

### 4.7 Errors (`app/core/errors.py`)

- `AppError(status_code, detail)` is our own exception type. Service code can raise, for example, `AppError(503, "LLM provider not configured")`, and an **exception handler** converts it into a JSON response with that status.
- A second handler catches any unexpected `Exception`, logs the full stack trace, and returns only `{"detail": "Internal server error"}`. Clients never see internals such as file paths or SQL, which would be a security leak.
- Validation errors (wrong types, missing fields) are handled by FastAPI itself, which returns **422 Unprocessable Entity** with details.

### 4.8 Middleware (`app/api/middleware.py`)

Middleware wraps every request. Ours:
1. Reads the `X-Request-ID` header if the client sent a safe-looking one, otherwise generates a random id.
2. Stores it in a `ContextVar`, so every log line during that request can include it.
3. Adds `X-Request-ID` to the response headers.
4. Logs one access line: method, path, status and duration.

A request id lets you find every log line for one user's failing call, even across services. It's standard in production APIs.

**ASGI** is the interface between the server (uvicorn) and the app (FastAPI). An ASGI app is an `async` callable taking `(scope, receive, send)`. We wrote the middleware in this raw form rather than with Starlette's `BaseHTTPMiddleware` because the raw form passes **streamed** responses through untouched. We'll need that for `/ask/stream`.

A **`ContextVar`** is like a global variable, except each request (each async task or thread context) sees its own value. That's why concurrent requests don't mix up their ids.

### 4.9 Logging (`app/core/logging.py`)

All our loggers are named `app.*` (via `logging.getLogger(__name__)`). `configure_logging()` attaches one handler to the `app` logger with the format:

```
2026-09-18 12:36:28,610 INFO app.access [90655272fc19...] GET /health 200 49.8ms
```

The filter copies the request id from the `ContextVar` into every record.

### 4.10 Tests (`tests/`)

```bash
uv run pytest -q
```

- **pytest** finds files named `test_*.py` and functions named `test_*`, and uses plain `assert`.
- **Fixtures** (`@pytest.fixture` in `conftest.py`) create objects that tests request by naming them as parameters. For example, `def test_x(client):` receives a ready `TestClient`. `conftest.py` is shared by every test in the folder.
- **`TestClient`** sends HTTP requests to the app in memory, with no real server or port. Using it in a `with` block runs the lifespan.
- **Fakes instead of real services.** `FakeEmbedder` turns text into a vector by hashing its words. It's deterministic, instant and needs no download, yet texts that share words still get similar vectors, so search ranking behaves sensibly in tests. The store uses Chroma's in-memory `EphemeralClient` with a random collection name per test, so tests never see each other's data.
- **Unit vs integration.** `tests/unit/` tests one piece in isolation (settings validation). `tests/integration/` tests through HTTP (health, request id, 500 handling).

### 4.11 Tooling

| Tool | Command | What it catches |
|---|---|---|
| ruff | `uv run ruff check .` and `uv run ruff format .` | Style issues, unused imports, likely bugs, import order, plus consistent formatting |
| mypy (strict) | `uv run mypy` | Type errors, such as passing a `str` where an `int` is expected, or forgetting to handle `None` |
| pre-commit | `uv run pre-commit install` (once) | Runs the checks automatically on every `git commit` and blocks the commit if any fail. It also blocks accidentally committed private keys. |
| GitHub Actions | `.github/workflows/ci.yml` | Runs ruff, mypy and pytest on every push and pull request, so broken code can't reach `main` unnoticed. |

The configuration for ruff, mypy and pytest lives in `pyproject.toml` under `[tool.ruff]`, `[tool.mypy]` and `[tool.pytest.ini_options]`.

The pre-commit hook flagged `uv.lock` (699 KB) as a "large file". Lockfiles are meant to be committed, so we excluded it from that one check.

### 4.12 Live check

```bash
uv run uvicorn app.main:create_app --factory --port 8765
curl -i http://localhost:8765/health
```

Result: `200 OK` with an `x-request-id` header. On first start, fastembed downloaded the model (about 65 MB) into `data/models/`. `/docs` also returned 200.

---

## Step 5 (Task 2): Chunking

Commit: `14a410c`, "Add recursive text chunker with overlap".

### Why chunk at all?

An embedding is one vector per piece of text. If you embed a whole 20-page document as one vector, its meaning gets averaged into mush, and search can't point at the paragraph that answers the question. LLM prompts also have a size budget. So documents are split into **chunks** of a few hundred characters, and each chunk gets its own vector.

### The algorithm (`app/services/chunking.py`)

1. **Split on the coarsest natural boundary that works.** Try paragraphs (`\n\n`) first. Any piece still too long is split on lines (`\n`), then sentences (`. `), then words (` `). Only a piece with no spaces at all (for example, a 300-character URL) is hard-cut at `size` characters. This is called *recursive character splitting*. LangChain popularised it, but it's about 30 lines, so we wrote it ourselves rather than adding a dependency.
2. **Pack pieces into chunks.** Add pieces to the current chunk until the next one would exceed `size`, then start a new chunk.
3. **Overlap.** Each new chunk starts with the last few pieces of the previous chunk, up to `overlap` characters. A sentence cut at a chunk boundary then still appears whole with its context in at least one chunk. Overlap is measured in whole pieces, so it never cuts a sentence mid-way.

Example with `size=100` and `overlap=40`:

```
chunk 1: "Sentence number 0 is here. Sentence number 1 is here. Sentence number 2 is here."
chunk 2: "Sentence number 2 is here. Sentence number 3 is here. Sentence number 4 is here."
          └─ carried over as overlap
```

Defaults are `CHUNK_SIZE=800` and `CHUNK_OVERLAP=120` characters: a few paragraphs per chunk, with 15% overlap.

### How it was built: test-driven development (TDD)

1. **Red:** wrote `tests/unit/test_chunking.py` first, and ran it to see it fail (the module didn't exist yet).
2. **Green:** wrote `chunk_text` until every test passed.
3. **Refactor:** tidied, with the tests as a safety net.

The tests pin down the behaviour: short text gives one chunk, blank text gives none, every chunk fits the size, no words are lost and order is kept, adjacent chunks overlap, paragraph boundaries are preferred, unbroken text is hard-cut, and invalid parameters raise `ValueError`.

---

## Step 6 (Task 3): Ingesting documents, `POST /documents`

This is the first *vertical slice*: one endpoint that goes all the way from HTTP request to stored vectors. The flow is:

```
JSON body -> validate (Pydantic) -> size check (413) -> chunk_text -> embed_documents -> replace_document -> 201
```

### 6.1 Request validation (`app/schemas/documents.py`)

`DocumentCreate` declares the body. Every rule that FastAPI can check on its own lives here, so a bad request never reaches our code and gets a **422** automatically:

- `text` must contain non-whitespace. A `field_validator` checks `text.strip()`.
- `document_id` must match `^[A-Za-z0-9._-]{1,128}$` (`Field(pattern=...)`). When absent, the route generates a UUID.
- `title` is at most 200 characters. When absent it's stored as `""`, because Chroma metadata can't hold `None`.
- `metadata` is `dict[str, str | int | float | bool]`. Pydantic rejects lists, nested objects and `null` because they match none of the union members. A second validator enforces at most 20 keys, the key pattern, and the reserved names `document_id`, `chunk_index` and `title`, which the server writes itself.

Pydantic's "smart" union mode keeps `true` as a `bool` rather than converting it to `1`, so types survive the round trip into Chroma.

### 6.2 Why the size limit is a 413, not a 422

The spec says a too-long document returns **413 Content Too Large**. A `max_length` on the field would produce a 422, and the schema can't see `Settings` anyway. So the route checks `len(body.text) > settings.max_document_chars` and raises `AppError(413, ...)`. The same `len(body.text)` is returned as `characters`, so the check and the response can never disagree.

### 6.3 Storing and replacing (`app/services/vector_store.py`)

`VectorStore.replace_document(document_id, chunks, embeddings, metadata, title)`:

1. Deletes every existing chunk whose metadata has this `document_id` (`collection.delete(where={"document_id": ...})`).
2. Adds the new chunks with ids `{document_id}:0`, `{document_id}:1`, ... Each chunk's metadata is the client's metadata plus `document_id`, `chunk_index` and `title`.

Deleting by metadata, not by computed ids, is what makes re-ingest safe. If the old version had 10 chunks and the new one has 3, computing ids from the *new* count would only overwrite `:0` to `:2` and leave `:3` to `:9` behind as orphans that still show up in search.

The route embeds *before* calling the store. If embedding fails, the old version of the document is still intact.

### 6.4 Tests (`tests/integration/test_documents.py`)

Written first (red), then the code (green). They cover the 201 body, the stored ids and metadata, the generated id, re-ingest with a shorter version (asserting the old last chunk id is gone, not just that the count dropped), other documents being untouched, the 413 limit and the exact boundary, and a parametrized list of 19 invalid payloads that must each return 422 and store nothing. The 422 tests assert only the status code, because the body of FastAPI's validation error is an implementation detail.

---

## Step 7: Product planning (after Task 3)

Before continuing with Task 4, we stepped back and planned what Sourcely becomes as a **product**, not just a PoC API. No code changed. The result is a set of documents in [`docs/product/`](product/README.md):

| Document | What it is | Why teams write it |
|---|---|---|
| [PRD](product/PRD.md) | Product requirements: problem, users, goals, features, phases, metrics, risks | Agrees *what* to build and *why* before anyone spends time on *how*. |
| [Wireframes](product/WIREFRAMES.md) | Low-fidelity screen layouts, including empty and error states | Cheap to change. Finds missing states before they become bugs. |
| [Interaction flows](product/INTERACTION_FLOWS.md) | How a user moves between screens to finish a job | Shows every decision point and dead end in a journey. |
| [Feature validation](product/FEATURE_VALIDATION.md) | Acceptance criteria, input rules, metrics, and assumptions to test first | Makes "done" testable, and checks the feature is worth building at all. |
| [Architecture](product/ARCHITECTURE.md) | Current and target system, data model, API surface, key decisions | Lets you reason about the whole system and its tradeoffs in one place. |
| [Flow diagrams](product/FLOW_DIAGRAMS.md) | Sequence diagrams and state machines for each operation | Shows the order of calls and where each error branches off. |
| [Data flow diagrams](product/DATA_FLOW.md) | Where data comes from, where it goes, where it's stored, and where it leaves the system | The basis for privacy and security reviews: you can't protect data you haven't traced. |

### Concepts worth knowing

- **Built, Specced, Proposed.** Every item in those documents carries one of these labels. A plan that mixes what exists with what's imagined, without saying which is which, misleads its readers.
- **Multi-tenancy.** One deployment serves many isolated customers (here, *workspaces*). The safest designs enforce isolation in more than one layer: the request, the code, and the database (PostgreSQL row-level security).
- **Background jobs.** Slow work (PDF extraction, embedding a large file) runs in a separate worker process, so the API answers quickly with `202 Accepted` and the client checks the status later.
- **Assumption testing.** Each risky belief (for example "users click citations") gets a cheap test *before* the feature is built. A failed test changes the plan, which is much cheaper than changing shipped code.

### What this does not change

`SPEC.md` is still the source of truth, and Task 4 is still next. The product documents are a proposal. Several ideas (auth, new endpoints, moving from Chroma to pgvector) are on the "ask first" list in `CLAUDE.md`, so each needs the owner's decision and a `SPEC.md` amendment before any code.

---

## Step 8 (Task 4): Semantic search, `POST /search`

The second vertical slice. It reuses everything Task 3 built: the same embedder turns the query into a vector, and the same Chroma collection finds the nearest chunks.

```
JSON body -> validate (Pydantic) -> embed_query -> VectorStore.query -> score = 1 - distance -> 200
```

### 8.1 Request and response models (`app/schemas/search.py`)

- `query` is 1 to 2,000 characters (`Field(min_length=1, max_length=2000)`) and must contain non-whitespace. The whitespace rule is the same `field_validator` pattern as document text. It was added to `SPEC.md` in this task, because a blank query has nothing to search for.
- `top_k` is `int | None` with `ge=1, le=20`. `None` means "use the `DEFAULT_TOP_K` setting". The route resolves it with `body.top_k or settings.default_top_k`. A `0` can never reach that line, because validation rejects it first.
- `SearchHit` has exactly the spec fields: `document_id`, `chunk_index`, `title`, `text`, `score`, `metadata`. Its `metadata` holds only the client's own keys, because the three reserved keys are already top-level fields.

### 8.2 Querying the store (`VectorStore.query`)

```python
result = self._collection.query(query_embeddings=[embedding], n_results=top_k,
                                include=["documents", "metadatas", "distances"])
```

Chroma answers a *batch* of query vectors, so every field in the result is a list of lists: one inner list per query vector. We send one vector, so we read index `[0]`. Each hit becomes a small frozen dataclass, `ChunkHit`, so the route never touches Chroma's raw result shape.

**Distance to similarity.** The collection was created with cosine space, so Chroma returns cosine *distance*. `score = 1 - distance` turns it into cosine similarity, where 1 means "same direction" and higher is better. The hits are sorted by score, highest first. Chroma already returns them in that order, but sorting in our code makes the contract explicit instead of depending on a library detail.

**Empty store.** We checked Chroma's behaviour directly: `n_results=0` raises `TypeError`, while an empty collection queried with `n_results=1` returns `[[]]`. Since `top_k` is always at least 1, an empty store naturally gives `results: []`, which is what the spec asks for. Asking for more results than exist returns what there is.

**Why a service type, not the Pydantic schema?** Services don't depend on HTTP shapes. `ChunkHit` belongs to the store, and the route maps it to `SearchHit`. The same `query` method will serve `/ask` in Task 5.

### 8.3 The route (`app/api/routes/search.py`)

Thin, as the layering rule requires: resolve `top_k`, embed the query, query the store, map hits to the response. It doesn't need the LLM, so `/search` works even when no LLM key is set. A test proves that.

### 8.4 Tests (`tests/integration/test_search.py`)

Written first and run red (18 failures, because the route didn't exist). They cover the empty store, the relevant document ranking first, the exact hit fields and the metadata filtering, scores sorted high to low with an identical query scoring 1.0, the `DEFAULT_TOP_K` fallback, `top_k` above the chunk count, search without an LLM key, 8 invalid payloads returning 422, and the boundary values (2,000 characters, `top_k` 1 and 20).

### 8.5 Live check with the real model

With the real `bge-small-en-v1.5` model and three short documents (leave policy, refunds, VPN), every question found the right document first, even with different wording: "how many vacation days do I get" matched the *leave* document, although the word "vacation" never appears in it. That is semantic search working.

| Query | Top hit and score | Other scores |
|---|---|---|
| how many vacation days do I get | leave 0.670 | 0.630, 0.454 |
| can I get my money back | refunds 0.688 | 0.494, 0.446 |
| connect to the company network remotely | vpn 0.709 | 0.450, 0.395 |
| what is the capital of France (off topic) | vpn 0.475 | 0.429, 0.402 |

The numbers matter for Task 5. Unrelated text scores 0.40 to 0.63, which overlaps with the relevant range. `MIN_RELEVANCE` therefore can't be guessed. It has to be chosen from a larger sample at Checkpoint B.

### 8.6 A tooling fix found on the way

`ruff format --check .` failed on `CLAUDE.md` and two docs: ruff 0.16 also formats Python code blocks inside Markdown, and it wanted to reflow illustrative snippets. CI runs that exact command, so it would have failed. `pyproject.toml` now excludes `*.md` from formatting.

---

## Step 9 (Task 5): Answering questions, `POST /ask`

The third vertical slice completes the RAG loop: retrieve the relevant chunks, give them to an LLM, and return its answer together with the sources it was given.

```
JSON body -> validate -> key check (503) -> embed_query -> VectorStore.query -> drop hits below MIN_RELEVANCE
          -> none left: fixed answer, no LLM call
          -> otherwise: numbered <source> prompt -> LLM -> answer + sources
```

### 9.1 Two provider adapters and one error type (`app/services/llm.py`)

`LLM` is a `Protocol`: anything with `provider`, `model` and `complete(system, user) -> LLMAnswer`. A Protocol is Python's *structural* typing: a class satisfies it by having the right attributes, without inheriting from it. That's why the test `FakeLLM` works with no base class.

- **`OpenAICompatibleLLM`** calls `chat.completions.create(model, max_completion_tokens, messages)`. With `OPENAI_BASE_URL` it talks to Gemini or Ollama instead of OpenAI, with no code change.
- **`AnthropicLLM`** calls `beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`. If Claude's safety classifiers decline a request, Anthropic re-runs it on a fallback model inside the same call. We still check `stop_reason == "refusal"` *before* reading the content, because the whole chain can decline. The answer reports `response.model`, the model that actually served it.
- **`create_llm(settings)`** picks the adapter with one `if`, and returns `None` when the key is missing. The app still starts: `/documents` and `/search` keep working, and `/ask` returns 503.

We checked the installed SDKs before writing the calls: `fallbacks` accepts `"default"` in anthropic 1.6, and both SDKs define `APITimeoutError` as a subclass of `APIConnectionError`, so one `except` covers both.

**Error mapping.** Each SDK raises its own exception classes. Both adapters translate them into one `LLMError(status_code, detail)`, so the route has a single `except`:

| Provider result | Our status | Why |
|---|---|---|
| 429, 503, 529 (rate limit, unavailable, overloaded) | 503 | Temporary. The client should try again later. |
| 408, 504, timeout, connection error | 504 | The provider didn't answer in time. |
| Anything else: 400, 401, 404, 500, refusal, empty answer | 502 | The upstream service rejected us or failed. It isn't the client's fault, so not a 4xx. |

The details are generic ("LLM provider rejected the request"). The provider's own message can contain account details, so it goes to the log as a status code only, never to the client.

### 9.2 The prompt

The system prompt sets five rules: use only the sources, cite every claim as `[n]`, say there is not enough information instead of guessing, treat the sources as data rather than instructions, and answer in the question's language.

The user message wraps each chunk in a numbered block:

```
<sources>
<source id="1" title="Leave policy">
Employees get 21 days of paid annual leave...
</source>
</sources>

Question: How much annual leave do part-time staff get?
```

Titles and texts are **HTML-escaped**. Without that, a document containing `</source>` followed by fake instructions could close its own block and pose as something else. A unit test proves the escaping.

### 9.3 Orchestration (`app/services/rag.py`)

`answer_question` retrieves, filters by `MIN_RELEVANCE`, and returns the fixed `NO_CONTEXT_ANSWER` without calling the LLM when nothing is left. Skipping the call saves money and avoids a confident answer built on unrelated text. It is a plain function over injected components, so it is easy to test and will be reused by the streaming endpoint in Task 9.

### 9.4 Why the key check comes first

The route returns 503 before any retrieval when the key is missing. The alternative, checking only when the LLM is about to be called, would make `/ask` answer 200 for off-topic questions and 503 for on-topic ones on the same misconfigured server. Failing consistently is easier to diagnose. `SPEC.md` and flow diagram FD-7 now say so.

### 9.5 Tests

- `tests/unit/test_llm.py` (32 tests) uses fake SDK clients that record the request. It checks the exact request each adapter sends (including `betas` and `fallbacks`), text joining, the served model, refusal and empty answers, every status mapping built from real SDK exception objects, prompt numbering and escaping, and the factory.
- `tests/integration/test_ask.py` (16 tests) uses `FakeLLM` from `conftest.py`. It checks the answer and sources, that the context and question reach the prompt, that irrelevant chunks are dropped, both no-context paths skipping the LLM, `top_k`, the missing key giving 503 while `/documents` and `/search` still work, error statuses passed through, and 422 validation.

### 9.6 Live check: the configuration caught a real problem

The first live `/ask` returned **502**. The test suite couldn't catch this, because it's configuration: `.env` held an OpenAI key (`sk-proj-…`) next to the Gemini base URL. Gemini answered **400 "Please pass a valid API key"**. Gemini reports a bad key as 400, not 401, and our mapping turned it into a 502 with a safe message, as designed. The off-topic question in the same run returned the fixed answer in 39 ms with no LLM call. The full live check waits for a valid key at Checkpoint B.

---

## Step 10: Checkpoint B, live check and calibration

A checkpoint is where the owner reviews real behaviour before more features are built on top. This one checks the whole RAG loop against the real embedding model and the real LLM, and sets the one number that can't be guessed: `MIN_RELEVANCE`.

### 10.1 A configuration trap: environment variables beat `.env`

After the Gemini key was added to `.env`, the app still sent the old OpenAI key. The cause: a Windows user-level environment variable `OPENAI_API_KEY`. pydantic-settings reads real environment variables **before** the `.env` file, so the variable silently won. That order is deliberate, and it's the twelve-factor convention: in Docker or production, configuration comes from the environment, and a stray file shouldn't override it. The fix belongs to the machine, not the code. Until the variable is removed, live checks run with `env -u OPENAI_API_KEY`.

Also learned: newer Google AI Studio keys start with `AQ.`, not only `AIza`.

### 10.2 Live end-to-end check

With the real `bge-small-en-v1.5` model and Gemini `gemini-3.5-flash-lite`:

| Question | Answer | Sources | Time |
|---|---|---|---|
| How long is parental leave for partners? | "Partners are entitled to 4 weeks of paid parental leave [1]." | leave 0.826 | 4.9 s |
| Can I get a refund on a monthly plan? | "No, monthly plans are not refundable [1]." | refunds 0.810 | 1.0 s |
| What is the capital of France? | Fixed "not enough information" answer, no LLM call | none | 0.1 s |

The first LLM call is slower because it opens the connection. A restart with the same `CHROMA_PATH` kept both chunks, and search still found the right document, so persistence works.

### 10.3 Calibrating `MIN_RELEVANCE`

A threshold separates "relevant enough to answer from" from "don't answer". It must come from measurements on the actual model, because small embedding models give unrelated text surprisingly high similarity.

The corpus was 6 short policy documents (leave, refunds, VPN, expenses, security, onboarding), 14 questions they answer (worded differently from the documents, like "vacation days" for "annual leave"), and 8 they don't (general knowledge, and plausible company questions with no document). Only embeddings were used, so it cost nothing.

| | Right document's score | Unanswerable questions' best score | Gap |
|---|---|---|---|
| Plain query | 0.609 to 0.824 | up to 0.589 | 0.020 |
| With bge's query prefix | 0.607 to 0.794 | up to 0.555 | **0.052** |

Both put the right document first for 13 of 14 questions.

**The query prefix.** BAAI trained bge with the instruction "Represent this sentence for searching relevant passages: " in front of queries. We had verified in Task 1 that fastembed does *not* add it. Measured here, adding it lowers all scores a little, but it lowers unrelated ones more, so the gap grows 2.6 times. The plan said to adopt it only if it measurably helped, and it did. It's added to **queries only**: documents are embedded as they are.

**The threshold.** `0.58` is the middle of the prefixed gap (0.555 to 0.607). It blocked all 8 unanswerable questions and kept all 14 answerable ones. The old placeholder of 0.5 would have sent 5 of the 8 unanswerable questions to the LLM. Choosing the middle of the gap leaves room for error on both sides.

**The limit of this evidence.** 22 questions on 6 short documents is a small sample. The threshold should be rechecked on real documents, and it must be recalibrated whenever the embedding model or the prefix changes, because both shift every score.

### 10.4 Code changes

- `FastEmbedEmbedder(model, cache_dir, query_prefix)` prepends the prefix in `embed_query` only. Three unit tests use a fake fastembed model to prove the prefix reaches queries and never documents.
- New setting `EMBEDDING_QUERY_PREFIX`, defaulting to bge's instruction. `MIN_RELEVANCE` now defaults to `0.58`.
- Re-checked through the real app: "Do part-time workers get holiday?" scored 0.713 and got a cited answer; "Can I bring my dog to work?" got the fixed answer without an LLM call.

---

## Step 11 (Task 6): File upload, `POST /documents/upload`

Clients can now send a `.txt` or `.md` file instead of JSON. The rules are the same as `POST /documents`, so both routes now share one ingest step.

```
multipart form -> extension check (415) -> read with a byte cap (413) -> decode UTF-8 (422)
               -> blank check (422) -> same path as POST /documents -> 201
```

### 11.1 Multipart form data

A browser or `curl -F` sends files as `multipart/form-data`: the body is split into *parts*, one per field, each with its own headers. FastAPI parses it with the `python-multipart` package, added with `uv add python-multipart` (it was already in the spec's tech stack, so no approval was needed).

```python
def upload_document(
    file: Annotated[UploadFile, File(description="A UTF-8 `.txt` or `.md` file")],
    ...,
    document_id: Annotated[str | None, Form(pattern=DOCUMENT_ID_PATTERN)] = None,
)
```

`UploadFile` gives the file name and a file object. `Form(pattern=...)` validates the optional `document_id` exactly like the JSON route does, so a bad id is a 422 before our code runs.

### 11.2 The checks, in order

1. **Extension** (`415 Unsupported Media Type`): `.txt` or `.md`, in any case. `archive.txt.zip` is rejected because only the last extension counts.
2. **Size, in bytes, before decoding** (`413`): the route reads at most `4 × MAX_DOCUMENT_CHARS + 1` bytes. A UTF-8 character takes at most 4 bytes, so anything bigger can't be within the character limit. This keeps a huge upload from being loaded into memory whole.
3. **Encoding** (`422`): decoded with `utf-8-sig`, which also removes the *byte order mark* that some Windows editors put at the start of UTF-8 files. Without that, the first chunk would start with an invisible character.
4. **Blank** (`422`): an empty or whitespace-only file.
5. **Size, in characters** (`413`): the same check as the JSON route. A test proves the limit counts characters, not bytes: 5,000 `é` characters (10,000 bytes) are accepted at a 5,000-character limit.

The title is the file's base name. `PureWindowsPath(name).name` drops any path a client sends (`C:\Users\me\notes.txt` or `/home/me/notes.txt` both become `notes.txt`), because it splits on both kinds of slash. It's cut to 200 characters, the title limit.

### 11.3 Refactor: one ingest path

The chunk, embed and store steps moved from the JSON route into `app/services/ingestion.py` (`ingest_text`), following the rule that logic lives in services. Both routes call a small `_ingest` helper that applies the character limit and generates the id. The Task 3 tests passed unchanged, which shows the refactor kept the behaviour.

### 11.4 Tests (`tests/integration/test_upload.py`)

22 tests, written first and run red: the 201 body with the file name as title, `.md` and mixed-case extensions, the generated id, replace on re-upload, the uploaded text being searchable, BOM removal, client paths stripped from the title, long names cut to 200 characters, 4 rejected file types (415), non-UTF-8 (422), empty and blank files (422), a bad id (422), a missing file (422), the limit and its exact boundary (413 and 201), and characters counted rather than bytes.

### 11.5 A limit that remains

Starlette writes the whole upload to a temporary file *before* the route runs. The byte cap limits what we read, not what the server receives. The request size itself should be capped in front of the app, which is part of Task 10 (Docker).

---

## Step 12 (Task 7): Listing and deleting documents

Two small endpoints that make the store manageable: see what's in it, and remove what shouldn't be searchable any more.

### 12.1 `GET /documents`: rebuilding documents from chunks

Chroma stores *chunks*, not documents. There is no document table to read. So `VectorStore.list_documents()` reads the metadata of every chunk (`collection.get(include=["metadatas"])`), groups by `document_id`, counts the chunks, and takes the title and client metadata from the first chunk of each group. Every chunk of a document carries the same title and metadata, because `replace_document` writes them onto each one. The result is sorted by `document_id`.

**The cost** grows with the number of *chunks*, not documents: listing 10 documents of 1,000 chunks each reads 10,000 metadata records. That's fine for a PoC and was accepted in `SPEC.md` as a known scaling limit. The product plan fixes it with a real `documents` table in Postgres.

`include=["metadatas"]` matters: without it, Chroma would also return every chunk's text, and embeddings can be requested too. Asking only for what's needed keeps the call light.

### 12.2 `DELETE /documents/{document_id}`

```python
existing = self._collection.get(where={"document_id": document_id}, limit=1, include=[])
if not existing["ids"]:
    return False
self._collection.delete(where={"document_id": document_id})
```

The existence check fetches at most one chunk id and nothing else (`include=[]`), because we only need to know whether any chunk exists. Chroma's `delete` doesn't report how many rows it removed, so without the check we couldn't tell a real delete (204) from an unknown id (404).

**204 No Content** means "done, and there is nothing to return". The route returns a bare `Response(status_code=204)`, so the body is truly empty, which is what HTTP requires for a 204.

**Path validation.** `Path(pattern=DOCUMENT_ID_PATTERN)` applies the same id rule as ingestion. An id that could never have been stored (`has space`, 129 characters) gets **422**, a malformed request, rather than 404.

**Not atomic.** Check-then-delete is two calls. If two clients delete the same id at the same moment, both may see it and both get 204. The outcome is still correct (the document is gone), so a PoC can accept that.

### 12.3 Naming

The store returns a frozen dataclass `StoredDocument`, and the route maps it to the Pydantic `DocumentSummary`. Two different names keep the service type and the HTTP shape from being confused, the same split as `ChunkHit` and `SearchHit`.

### 12.4 Tests (`tests/integration/test_manage_documents.py`)

9 tests, written first and run red: the empty list, sorting with titles, chunk counts and client metadata only, the list after a shorter re-ingest, an uploaded file appearing with its file name as title, delete returning an empty 204 and removing every chunk while other documents stay, the deleted document disappearing from `/search`, 404 for an unknown id and for a second delete, and 422 for invalid ids.

---

## Step 13 (Task 8): Filters on `/search` and `/ask`

Clients can now limit which chunks may match: only certain documents, only certain metadata values, or both.

```json
{ "query": "refund window", "filters": { "document_ids": ["refunds", "billing-faq"], "metadata": { "source": "wiki" } } }
```

### 13.1 Validation (`SearchFilters` in `app/schemas/search.py`)

- `document_ids`: 1 to 100 ids, each matching the same id pattern as ingestion. `Annotated[str, StringConstraints(pattern=...)]` applies a rule to *each item* of a list.
- `metadata`: 1 to 10 pairs with the ingestion key and value rules. The key rules moved into one function, `check_metadata_keys`, used by both ingestion and filters, so the two can't drift apart.
- `model_config = ConfigDict(extra="forbid")`: an unknown field is a 422. By default Pydantic *ignores* unknown fields. For filters that would be dangerous: a client who wrote `"document_id"` instead of `"document_ids"` would get no error and silently search everything.
- `filters: null` and `filters: {}` both mean "no filter".

### 13.2 From filters to a Chroma `where` clause (`build_where`)

| Filters | `where` clause |
|---|---|
| none | `None` |
| `document_ids: ["a", "b"]` | `{"document_id": {"$in": ["a", "b"]}}` |
| `metadata: {"source": "wiki"}` | `{"source": {"$eq": "wiki"}}` |
| several conditions | `{"$and": [condition, condition, ...]}` |

`build_where` is a **pure function**: plain data in, plain data out, no Chroma call. That makes it trivial to unit-test, which is why the plan kept it separate. One Chroma detail it handles: `$and` must have at least two items, so a single condition is returned unwrapped.

Filtering happens **inside** the nearest-neighbour search, not after it. Chroma only considers chunks that match `where`, so asking for `top_k=4` still returns up to 4 matching chunks. Filtering the top 4 afterwards could return fewer, or none.

The same `where` goes through `/ask`: `retrieve_relevant` passes it to the store, so an answer can only cite allowed documents. If the filter leaves nothing relevant, `/ask` returns the fixed answer without calling the LLM.

### 13.3 Tests

- `tests/unit/test_vector_store.py` (15 tests): `build_where` for every shape, then filtered queries against a real in-memory Chroma collection. Its vectors are nearly identical on purpose, so similarity can't decide the result and only the filter does. It covers `str`, `int`, `bool` and `float` values, AND between metadata pairs, AND between ids and metadata, and filters that match nothing.
- `tests/integration/test_filters.py` (33 tests): filtered `/search` and `/ask` over HTTP, `null` and `{}` filters, an `/ask` filter that excludes every relevant document (fixed answer, no LLM call), 12 invalid filter shapes on both endpoints, and the inclusive limits (100 ids, 10 pairs).

---

## Step 14 (Task 9): Streaming answers, `POST /ask/stream`

The answer now arrives as it's written instead of all at once. This is the most delicate endpoint, because once a streamed response starts, its HTTP status can't change.

### 14.1 Server-Sent Events

SSE is a simple text format on top of a normal HTTP response with `Content-Type: text/event-stream`. Each event is a few `field: value` lines followed by a blank line:

```
event: sources
data: {"sources": [...], "provider": "openai", "model": "gemini-3.5-flash-lite"}

event: token
data: {"text": "Part-time staff receive annual leave"}

event: done
data: {}
```

`data` is JSON, so a newline inside the answer text becomes `\n` and can't end the event early.

### 14.2 The key design: fetch the first token before sending headers

A normal response sends its status and headers at the end, when everything is known. A streamed response sends them **at the start**. After that, a failure can't become a 503 any more: the client has already received `200 OK`.

Most failures happen at the very start: a missing or wrong key, a rate limit, a timeout, a refusal. So `start_answer_stream` in `app/services/rag.py` does all the risky work *before* the route builds the response:

1. Retrieve the sources (a relevance miss gives the fixed answer, with no LLM call).
2. Open the provider stream and call `next()` once to get the **first token**.
3. Return the sources plus `chain([first], rest)`, an iterator that replays that first token and continues with the rest.

If step 2 raises `LLMError`, the route turns it into a normal 502, 503 or 504 with a JSON body. Only failures *after* the first token become an `event: error` inside the 200 stream.

### 14.3 Adapter streaming (`app/services/llm.py`)

Each adapter gained `stream(system, user) -> Iterator[str]`, a generator that yields non-empty text deltas.

- **OpenAI-compatible**: `chat.completions.create(..., stream=True)`. It skips chunks with no `choices` (some servers send usage or keep-alive chunks) and `None` or empty deltas. The plan listed this as a risk for Gemini's compatibility layer, and the guards are in place.
- **Anthropic**: `with client.beta.messages.stream(...) as stream: for text in stream.text_stream`. After the text ends, `get_final_message().stop_reason` is checked. With server-side fallbacks, a model that declines mid-answer is replaced *on the same stream* and the text simply continues. So only a final `refusal`, meaning the whole fallback chain declined, becomes an error.
- Both raise `LLMError(502)` if the stream ends without any text.

**One error-mapping function per SDK.** The SDK-to-`LLMError` translation became a context manager (`_openai_errors`, `_anthropic_errors`) built with `@contextmanager`. `complete()` and `stream()` both wrap their SDK calls in it, so a timeout means 504 in both, without duplicated `except` blocks. It also catches the SDKs' base `APIError`, which is what a provider's error event *inside* a stream raises. That kind of error has no HTTP status of its own, so it maps to 502.

### 14.4 The route (`app/api/routes/ask.py`)

The route returns `StreamingResponse(_sse_events(stream), media_type="text/event-stream")` with two extra headers:

- `Cache-Control: no-cache`, so nothing caches a live answer.
- `X-Accel-Buffering: no`, which tells nginx-style proxies not to buffer the response. A buffering proxy would collect every token and deliver them all at the end, defeating the point.

`_sse_events` is a plain (sync) generator. Starlette runs it in its threadpool, the same way it runs our `def` routes, so blocking SDK iteration never blocks the event loop.

**Mid-stream errors.** `LLMError` becomes `event: error` with its safe detail. Any other exception is logged with its full trace and becomes `event: error` with the fixed text "The answer was interrupted". The generic 500 handler can't help there, because the status line has already been sent. A test checks that an internal message ("socket details that must not leak") never reaches the client.

The raw ASGI middleware from Task 1 passes the stream through unbuffered. The access log records the full duration when the stream ends: `POST /ask/stream 200 4594.0ms`.

### 14.5 Tests

- `tests/unit/test_llm.py` (+10): the exact streaming request for each SDK (`stream=True`; `betas` and `fallbacks`), skipping empty chunks and deltas, errors when the stream opens and in the middle of it, content filter, a refusal before and after partial text, an empty stream, and the Anthropic stream context manager being closed.
- `tests/integration/test_ask_stream.py` (16): event order, tokens joining to the full answer, the `sources` payload, headers, the no-context path with no LLM call, filters, 502/503/504 before the first token as real HTTP errors with JSON, an `LLMError` and an unexpected exception after the first token as `error` events, a missing key (503), and validation (422). A small parser in the test splits the body into `(event, data)` pairs.

### 14.6 Live check

A real `uvicorn` server with Gemini, read with `curl -N`. The `sources` event came first, then 5 `token` events over about 2 seconds, then `done`. Gemini sends phrase-sized pieces ("Part-", then "time staff receive annual leave that is pro-rated based on their contracted hours", ...) rather than single words. The answer cited `[1]` throughout.

---

## Step 15 (Task 10): Docker, and a request size limit

The whole service now starts with one command, `docker compose up --build`. This task also closed the gap found in Task 6: the size of a request body is now limited before the server stores it.

### 15.1 The request size limit (`RequestSizeLimitMiddleware`)

Task 6 noted that Starlette writes an upload to a temporary file *before* any route runs, so a route can't stop a huge upload from being received. The fix belongs in front of the routes, so it's another raw ASGI middleware in `app/api/middleware.py`:

1. If the request declares `Content-Length` and it's larger than `MAX_REQUEST_BYTES`, reply **413** at once, without reading a byte of the body. A non-numeric `Content-Length` gets **400**.
2. A *chunked* request (`Transfer-Encoding: chunked`) has no declared length. The middleware wraps `receive` and counts bytes as they arrive. Past the limit, it raises an exception to stop reading.

One detail took a test to find: FastAPI catches any exception raised while reading a JSON body and answers **400** "There was an error parsing the body". So the middleware also wraps `send`. Once the limit is exceeded, it swallows whatever the app tries to send and sends its own 413 instead.

**Why a middleware and not a reverse proxy?** A proxy (Caddy, nginx) could enforce the same limit, but it would be one more container to run, and the app would be unprotected whenever it runs without the proxy (locally, in tests). The middleware works everywhere and has tests. A production proxy can add its own limit as a second layer.

**The default is 2 MiB.** A maximum-size document is 200,000 characters. In the worst case, JSON escapes every character as a 6-byte `\uXXXX`, which is 1.2 MB. A test checks that the default always leaves room for that, so the two limits can't contradict each other.

Middleware order matters. Starlette runs the **last added** middleware **first**. The size limit is added before `RequestContextMiddleware`, so the request-id middleware wraps it, and 413 responses still carry an `X-Request-ID` and an access-log line.

### 15.2 The Dockerfile

```
build stage:   python:3.12-slim + uv 0.9.22  ->  uv sync --frozen --no-dev --no-install-project  ->  /app/.venv
runtime stage: python:3.12-slim  +  /app/.venv  +  app/   ->  user sourcely, port 8000, health check
```

- **Multi-stage build.** The first stage installs dependencies; the second copies only the result. uv, its download cache and build files never reach the final image.
- **Layer caching.** Docker caches each step. `pyproject.toml` and `uv.lock` are copied and installed *before* `app/`, so editing code doesn't reinstall every package.
- **`--frozen`** installs exactly what `uv.lock` says and fails if the lock is out of date. **`--no-dev`** leaves out pytest, ruff and mypy.
- **Non-root.** The container runs as `sourcely` (uid 10001), which owns only `/app/data`. If the app were compromised, the attacker couldn't change the installed code.
- **Health check.** Docker calls `/health` every 30 seconds, using Python's `urllib` because the slim image has no `curl`. The 120-second start period covers the first model download.
- **`.dockerignore`** keeps `.env`, `.venv/`, `data/`, `.git/`, tests and docs out of the build context. The key point is that **`.env` never enters the image**: configuration arrives at run time instead.

### 15.3 docker-compose.yml

- `env_file: .env` with `required: false`: configuration is read at run time, and the API still starts without it (`/ask` then returns 503).
- `CHROMA_PATH` and `EMBEDDING_CACHE_DIR` are fixed to the container paths, so a local `.env` with host paths can't break them.
- Named volumes `chroma-data` and `model-cache` survive `docker compose down`, restarts and rebuilds. `docker compose down -v` deletes them.

### 15.4 A bug only the container showed

The first container failed to start with `Permission denied (os error 13)` while downloading the embedding model. The Hugging Face download library keeps its own cache in the user's **home directory**, and the `sourcely` user was created without one. The fix sets `HF_HOME=/app/data/models/.huggingface`, inside the writable model volume. The tests could never have caught this, because they don't download models or run as a restricted user.

### 15.5 Verification

- `tests/integration/test_request_limit.py` (8 tests): a body exactly at the limit is accepted; a declared length over it gets 413 with a request id and nothing stored; chunked bodies over and under the limit; an oversized upload; an invalid `Content-Length` (400); GET requests unaffected; and the default fits the largest valid document.
- In Docker: healthy about 30 seconds after start; `/health` 200; ingest 201; search found the right document (0.656); a live `/ask` through Gemini answered "No, monthly plans are not refundable [1]."; a 2.2 MB upload got 413; the process runs as `sourcely`; after `docker compose restart`, `chunks_indexed` was still 1 and the model wasn't downloaded again.

---

## Step 16 (Task 11): README and final verification

The last task produces no new behaviour. It makes the project usable by someone else, and proves the spec is met.

### 16.1 The README

`README.md` is written for a developer who has just cloned the repository. It covers the two ways to run the service (Docker, or uv), getting a free Gemini key, switching to OpenAI, Claude or Ollama, a curl example with real output for every endpoint, the error statuses, configuration, a short architecture tour, known limits and next steps. It states plainly that the Claude path is untested live, and puts the free-tier data warning near the top, where people will see it.

It also records two traps found during the build: environment variables override `.env` (the Checkpoint B problem), and `uvicorn app.main:app` doesn't work because the app is built by a factory.

### 16.2 Verifying the README by following it

Documentation drifts from code silently, so the README was checked by *running* it: a fresh server with an empty index, then every curl command exactly as written. All of them worked. Two example values were wrong (the character count was 129, not 130, and a search score was 0.65, not 0.71), so they were corrected to the real output.

### 16.3 Evidence for every success criterion

`SPEC.md` listed eight success criteria at the start. Each one now has recorded evidence under "Evidence" in `SPEC.md`: a test name, a live run, or both. Writing the criteria before building, and the evidence after, is what makes "done" checkable instead of a feeling.

---

## Step 17 (Task 12): Postgres foundation

Phase 1 starts here. This task adds the database and everything around it (containers, roles, migrations, test database, CI) without any business tables yet, so later tasks only add tables and routes.

### 17.1 Postgres in Compose, with two roles

`docker compose up -d db` starts `pgvector/pgvector:pg17`. The plain `postgres` image has no `vector` extension. On first start, `docker/postgres/init.sql` creates:

- **`sourcely_owner`**, which owns the database and runs migrations;
- **`sourcely_app`**, which the API uses. It can read and write rows but owns nothing.

Why two? Row-level security (Task 16) filters rows per workspace, but a table's **owner bypasses it** by default. If the app connected as the owner, isolation could silently not apply. A test (`test_app_role_cannot_create_tables`) proves the app role can't even create a table.

`ALTER DEFAULT PRIVILEGES FOR ROLE sourcely_owner ... GRANT SELECT, INSERT, UPDATE, DELETE ... TO sourcely_app` means every table the owner creates later is automatically usable by the app, with no grant in each migration.

### 17.2 Two Windows surprises

- **Ports.** 5432 and 5433 were already used by two other local projects, so Sourcely publishes on **5434**.
- **`localhost` is slow.** Connecting to `localhost` took **15 seconds**, to `127.0.0.1` 0.04 seconds. Windows resolves `localhost` to IPv6 `::1` first; the container listens only on IPv4, and the attempt waits for a timeout before falling back. All URLs use `127.0.0.1`, and a config test guards against a regression.

### 17.3 Migrations with Alembic

A **migration** is a versioned script that changes the schema: `0001` creates X, `0002` adds Y. Each database records its version (the `alembic_version` table), so `alembic upgrade head` applies only what's missing. That's how a schema changes without losing data.

- `migrations/env.py` reads the URL from settings (`MIGRATION_DATABASE_URL`), so credentials never go into `alembic.ini`.
- `app/db/models.py` imports every table, so Alembic's *autogenerate* can compare the models with the database.
- Migration `0001` only checks that the `vector` and `citext` extensions exist. Creating an extension needs a superuser, so `init.sql` and the test fixture create them.
- In Compose, a one-shot **`migrate`** service runs `alembic upgrade head` and exits; `api` starts only after it finished successfully (`condition: service_completed_successfully`).

### 17.4 The app side

- `create_app(..., engine=None)` builds the engine in the lifespan (or accepts one from a test), and disposes it on shutdown.
- `DbDep` gives a route one `Session` whose transaction commits when the route returns and rolls back if it raises.
- `/health` runs `SELECT 1`. If that fails it returns **503** "Database unavailable", because health checks and load balancers look at the status code.
- **Startup checks the embedding dimension.** The model's vectors must fit the `vector(384)` column Task 16 creates. A mismatch now stops the app at startup with a clear message, instead of failing on the first insert.

### 17.5 The 2-minute test

The first full run took 149 seconds instead of 20. `--durations` showed one test responsible for 130 of them: the "database is down" test, connecting to port 1. On Windows, when nothing listens, the attempt can be dropped rather than refused, and psycopg waited for the operating system's own timeout. A production outage would have stalled `/health` the same way. The fix is `connect_timeout=5` in `make_engine`, and the test passes an engine with a 1-second timeout. The suite is back to about 22 seconds.

### 17.6 The test database

- One **session-scoped** fixture creates `sourcely_test_<random>` as a superuser (`TEST_ADMIN_DATABASE_URL`), creates the roles if missing (so it works on a bare CI Postgres), adds extensions and grants, runs the migrations as the owner, and drops the database at the end with `DROP DATABASE ... WITH (FORCE)`.
- Before each test, every table except `alembic_version` is truncated, so tests don't see each other's rows.
- If Postgres isn't running, the run stops at once with "Start it with: docker compose up -d db", not with 237 connection errors.
- The fake embedder now returns 384-dimension vectors, to fit the column.
- CI runs the same image as a **service container** on port 5434.

All 237 tests pass (4 new: health with the database, 503 when it's down, the dimension check, and the app role's limits). The full Compose stack came up with `db` healthy, `migrate` exited 0, and `api` healthy.

---

## Step 18 (Task 13): Accounts and sessions

Sourcely now has users. People sign up, verify their email, sign in and out, and reset a forgotten password. Nothing is protected by it yet: Tasks 14 to 16 put the data endpoints behind it.

### 18.1 The tables (migration `0002`)

| Table | Purpose |
|---|---|
| `users` | Email (`citext`, unique, so `Ayesha@Example.com` and `ayesha@example.com` are the same account), name, Argon2id password hash, verified time |
| `sessions` | One row per signed-in browser: the **SHA-256 of the cookie value**, the CSRF token, and last-seen time |
| `email_tokens` | Single-use links for verification (24 h) and password reset (1 h), stored hashed |
| `login_attempts` | Failed sign-ins, for throttling |

The migration was made with `alembic revision --autogenerate`: Alembic compared `app/db/models.py` with the database and wrote the `create_table` calls. The migration template was updated so future files come out ruff-clean.

### 18.2 Passwords

- **Argon2id** (argon2-cffi) with a random salt per hash. See `TECH_STACK.md` for why it, and not SHA-256 or bcrypt.
- **Rules only when a password is set:** 12 to 128 characters, and not on the common-passwords list. Sign-in accepts any string, so tightening the rules later never locks anyone out.
- **The common-passwords list.** The spec first said "10,000 common passwords". Checking the popular 10k list showed only **10** of its entries are 12 characters or longer; with a 12-character minimum it would block almost nothing. So the bundled list (`app/core/common_passwords.txt`) is the 1,259 entries of 12 or more characters from the UK NCSC's 100,000 most-used passwords, like `q1w2e3r4t5y6` and `1qaz2wsx3edc`. Checking is case-insensitive. `SPEC.md` was updated to match.

### 18.3 Not revealing who has an account

An attacker can learn which emails are registered from any difference in the response, including its timing. So:

- **Sign-up** always returns the same `202`. For an existing email, nothing is created and the owner gets an "already have an account" email instead. The password is hashed in both cases, so both take equally long.
- **Sign-in** returns the same `401 "Email or password is incorrect"` for a wrong password and an unknown email. For an unknown email it still verifies a password against a dummy hash, so both paths spend the same Argon2 time.
- **Password reset** always returns the same `202`, and only sends mail when the account exists.

### 18.4 Sessions and CSRF

Signing in sets two cookies:

- `sourcely_session`: a random 32-byte token. **HttpOnly** (JavaScript can't read it, so an injected script can't steal it), **SameSite=Lax** (not sent on most cross-site requests), and **Secure** (HTTPS only; tests turn this off because the test client uses plain HTTP). The database stores only its SHA-256, so a leaked database can't be turned back into working cookies. A test checks this.
- `sourcely_csrf`: another random token, **readable** by JavaScript.

**CSRF** (cross-site request forgery) is another site making your browser send a request to Sourcely, carrying your cookie automatically. The defence: every `POST`, `PATCH`, `PUT` or `DELETE` made with a session must also send the CSRF token in an `X-CSRF-Token` header. The web app can read the cookie and copy it into the header; another site can't read it, so it can't forge the header. The comparison uses `secrets.compare_digest`, which takes the same time however many characters match.

Sessions expire after 14 days without use. `last_seen_at` is updated at most every 5 minutes, so reading `/me` doesn't write to the database every time.

### 18.5 Throttling, and a transaction trap

After 5 failed sign-ins for one email within 15 minutes, further attempts get **429** with `Retry-After`, even with the right password. Otherwise an attacker could keep guessing and just watch for the one success.

**The trap.** Each request runs in one transaction (`DbDep`), which **rolls back** when the route raises an error, and a failed sign-in *is* an error (401). Recording the failure in the request's transaction would undo it every time, and the throttle would never trigger. So `record_failed_login` writes in its own short transaction, which commits even though the request then fails.

### 18.6 Email

`EmailSender` is a protocol with one method, `send(message)`. Phase 1's `ConsoleEmailSender` writes the email, link included, to the log. Tests use an in-memory `FakeEmailSender` and read the token from `outbox.last(email)`. A real sender (SMTP or an email API) can replace it later without touching any route.

### 18.7 Tests

- `tests/unit/test_security.py` (9): Argon2id format and verification, salts, garbage hashes, token randomness and hashing, the common-password check.
- `tests/integration/test_auth.py` (28): sign-up emails for new and existing addresses, 7 validation cases, cookie attributes, single-use and expired verification links, sign-in (case-insensitive email, identical failures, unverified accounts), the throttle and its window, `/me`, CSRF on sign-out, idle expiry, only hashes stored, and password reset ending every session including another browser's.

Expired links and idle sessions are tested by moving timestamps back in the database (`owner_db` fixture), not by waiting.

A live run against the development database showed the verification email in the log, and `/auth/verify` then `/me` worked with it.

---

## Step 19 (Task 14): Workspaces, roles and the Principal

A **workspace** is the unit of isolation: from Task 16 on, every document belongs to exactly one. This task adds workspaces, the roles people have in them, and the object every later request is built on: the `Principal`.

### 19.1 Tables (migration `0003`)

- `workspaces`: id and name (1 to 60 characters).
- `memberships`: `(workspace_id, user_id)` as the primary key, and `role` checked to be `owner`, `admin`, `editor` or `viewer`. Deleting a workspace or a user cascades to their memberships.

**Exactly one owner, enforced by the database.** A **partial unique index** is an index over only the rows matching a condition:

```sql
CREATE UNIQUE INDEX uq_memberships_one_owner ON memberships (workspace_id) WHERE role = 'owner';
```

Among the owner rows, each workspace can appear once. However the application code changes later, the database refuses a second owner. A test inserts one directly and expects an `IntegrityError`.

### 19.2 The role table, in one place

`app/services/workspaces.py` names four **actions** and the least role allowed each:

| Action | Means | Least role |
|---|---|---|
| `read` | list documents, search, ask | viewer |
| `write` | add, replace, delete documents | editor |
| `manage` | rename; members, invites, API keys | admin |
| `own` | delete the workspace, transfer ownership | owner |

`allowed(role, action)` compares ranks. It's the only place the rules exist, so routes can't disagree. A unit test checks all 16 role and action pairs against the spec's table.

### 19.3 The Principal

Every data request from Task 16 on starts by answering "who is calling, in which workspace, with which role?". The answer is a small frozen dataclass:

```python
@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID | None      # a browser session...
    api_key_id: uuid.UUID | None   # ...or an API key (Task 15)
    workspace_id: uuid.UUID
    role: str
```

Two dependencies build it:

- **`PrincipalDep`** for data routes: the session, plus the workspace named in the **`X-Workspace-ID`** header. A user can belong to several workspaces, so each request must say which one.
- **`MemberDep`** for management routes, which name the workspace in the path (`/workspaces/{workspace_id}/...`).

Both answer **401** without a session, **404** "Workspace not found" for a workspace the caller doesn't belong to (and for an id that isn't a UUID), and **400** when the header is missing. Routes then call `require(principal, "manage")`, which answers **403**.

**Why 404 and not 403 for a stranger?** A 403 says "this exists, but you can't have it", which confirms the workspace exists. A 404 reveals nothing.

### 19.4 Endpoints

| Endpoint | Who | Result |
|---|---|---|
| `POST /workspaces` | any signed-in user | 201; the caller becomes owner |
| `PATCH /workspaces/{id}` | admin, owner | renamed |
| `DELETE /workspaces/{id}` | owner, with `confirm_name` | 204; everything in it goes (cascade) |
| `POST /workspaces/{id}/transfer` | owner | the member becomes owner; the old owner becomes admin |
| `GET /me` | signed in | now lists workspaces with roles, sorted by name |

**Transfer and the one-owner index.** Promoting the new owner first would, for one moment, mean two owners, and the index would reject it. So the code demotes the old owner, flushes that change to the database, and only then promotes the new one.

**Delete needs the name.** `DELETE` with `{"confirm_name": "Acme Support"}`: a wrong name is 400. It's a guard against deleting the wrong workspace, like the "type the name" box on GitHub.

### 19.5 Testing it

- `sign_in("email")`: a fixture that signs up, reads the token from the fake outbox, verifies, and returns a signed-in client. `csrf(client)` gives the header for writes.
- Other roles are arranged by inserting `memberships` rows directly, since inviting members is Task 17.
- A **probe route** is added to the app inside one test file only (`/_principal`), which returns the resolved Principal. That tests the dependency on its own, before any real route uses it.

44 new tests: 18 for the role table and 26 for the API (creation, validation, CSRF, rename per role, 404 for strangers and malformed ids, delete with confirmation and its cascade, transfer and its edge cases, the one-owner index, and the Principal's 401, 400 and 404 cases).

---

## Step 20 (Task 15): API keys

People sign in with sessions; programs use **API keys**. A key belongs to one workspace and acts in it with the editor role: it can read, search, ask and add documents, but it can't manage anything.

### 20.1 The key and what's stored

A key looks like `sk_live_` plus 43 URL-safe characters (32 random bytes). Only two things are stored (migration `0004`):

- the **SHA-256 of the whole key**, used to look the key up;
- the **first 12 characters** (`sk_live_7Hq2`), shown in lists so people can tell keys apart. Only 4 of those characters are random, far too few to guess the rest.

The full key is in the `201` response to `POST /workspaces/{id}/api-keys` and **nowhere else, ever**. That's the same pattern as GitHub or Stripe: if the key is lost, you revoke it and make a new one.

### 20.2 Endpoints

| Endpoint | Result |
|---|---|
| `POST /workspaces/{id}/api-keys` `{name}` | `201` with the full key, shown once |
| `GET /workspaces/{id}/api-keys` | Keys without secrets, with `last_used_at` and `revoked_at` |
| `DELETE /workspaces/{id}/api-keys/{key_id}` | `204`; the key stops working on its next request |

All three are for admins and the owner, signed in.

### 20.3 Two ways to be a Principal

`get_principal` now checks the `Authorization` header first:

- **`Bearer sk_live_...`**: look the key up by its hash. Unknown or revoked is **401**. The Principal is the key's workspace with role `editor`, `api_key_id` set and `user_id` empty. `X-Workspace-ID` is optional; if sent, it must name the key's workspace (**400** otherwise).
- **Otherwise**: the session and `X-Workspace-ID`, as in Task 14.

Three rules keep the two paths apart:

- **Not both.** A request with a session cookie *and* a key is **400**. Otherwise it would be unclear whose permissions apply.
- **Keys can't act as a person.** Anything that uses `SessionDep` (`/me`, creating or managing workspaces, managing keys) answers a key with **403**. A leaked key can't create more keys or add members.
- **No CSRF for keys.** CSRF exists because browsers attach cookies automatically. A key is attached only by the program that holds it, so a forged cross-site request can't carry it.

`last_used_at` is updated at most once a minute, so a busy integration doesn't write to the database on every request.

### 20.4 Tests

- `tests/unit/test_api_key_generation.py` (4): format, uniqueness over 1,000 keys, how much the prefix reveals, and the stored hash.
- `tests/integration/test_api_keys.py` (21): the key shown once and only its hash stored, name validation, role and stranger checks, CSRF on creation, the key resolving to an editor Principal, the workspace header rule, 4 kinds of bad credential, revocation taking effect at once, another workspace's key (404), deleting a workspace killing its keys, cookie plus key (400), keys refused on 5 session-only endpoints, and the once-a-minute `last_used_at`.

The suite now takes about a minute, because each signed-in test user costs two Argon2 hashes.

---

## Step 21 (Task 16): Tenant data on pgvector

The core of Phase 1. Documents, chunks and vectors move from Chroma into Postgres, every data route requires a `Principal`, and three independent layers keep workspaces apart.

### 21.1 Tables (migration `0005`)

- `documents`: primary key `(workspace_id, document_id)`, so the same id can exist in two workspaces. Title, metadata as `jsonb`, and timestamps. This table also fixes the PoC's slow listing: `GET /documents` no longer reads every chunk.
- `chunks`: primary key `(workspace_id, document_id, chunk_index)`, the text, and `embedding vector(384)`. A foreign key to `documents` with `ON DELETE CASCADE` means deleting a document deletes its chunks in the same statement.
- An **HNSW index** with `vector_cosine_ops`: the same kind of approximate nearest-neighbour graph Chroma used, now inside Postgres.

### 21.2 Row-level security

**Row-level security (RLS)** lets the database filter rows per query. Migration `0005` turns it on for both tables with one policy:

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
  USING      (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
  WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);
```

- `USING` filters what can be **read, updated or deleted**; `WITH CHECK` what can be **written**.
- Each request sets the workspace on its transaction: `SELECT set_config('app.workspace_id', :id, true)`. The `true` makes it **transaction-local**, like `SET LOCAL`, so a pooled connection can't carry one request's workspace into the next. A test proves it.
- **When the setting is missing**, the comparison is NULL and no row matches. Forgetting to set it hides everything; it never shows everything.
- **Why `NULLIF`?** After a transaction-local setting ends, a reused connection reports `''`, not NULL, and `''::uuid` is an error.
- This only works because the app connects as `sourcely_app`, which **doesn't own** the tables (Task 12). Owners bypass RLS.

**The count for `/health`.** `/health` shows the chunk count for the whole deployment, which RLS hides from the app role. `chunk_count()` is a `SECURITY DEFINER` function: it runs with its owner's rights and returns only a number. Its `search_path` is pinned, a standard precaution for such functions.

### 21.3 `PgVectorStore` and `WorkspaceIndex`

`PgVectorStore` implements the same operations as the Chroma store, in SQL through SQLAlchemy and pgvector:

- **Score:** `1 - (embedding <=> query)`, cosine distance. Exactly the PoC's definition, so `MIN_RELEVANCE` keeps its meaning.
- **Filters:** `document_id IN (...)`, and JSONB **containment** `metadata @> '{"source": "wiki"}'` for metadata. Containment keeps typed matching: the number `2026` doesn't match the string `"2026"`.
- **Filtered searches keep their top-k.** An HNSW scan normally gathers a fixed number of candidates and then filters them, so a strict filter could leave fewer than `top_k`. pgvector 0.8's `hnsw.iterative_scan = relaxed_order` keeps scanning until it has enough. A test puts 60 closer non-matching chunks in front of 5 matching ones and still gets 4 results.
- **Replace is one transaction:** upsert the document row, delete its chunks, insert the new ones. The PoC's "not fully atomic" note no longer applies, and a test shows a failure halfway leaves the old version intact.

Every method takes the session and the workspace. `WorkspaceIndex` bundles store, session and workspace, and `IndexDep` builds it **after** setting `app.workspace_id`. Routes and services only ever see a `WorkspaceIndex`, so they can't query without a workspace.

### 21.4 Routes

Every PoC route kept its path and body, and gained two dependencies: `PrincipalDep` (who is calling) and `IndexDep` (their workspace's data). Writes call `require(principal, "write")`, reads `require(principal, "read")`. Only `/health` stays public.

### 21.5 Tests

- **The test client authenticates with an API key.** The `api_key` fixture inserts a workspace and a key directly (no sign-up, so no Argon2 cost), and `client` sends it on every request. Nearly all PoC tests passed unchanged on the first run against Postgres.
- Tests that inspected Chroma directly now use `store`, a read-only probe over Postgres (connected as the owner, so it bypasses RLS).
- **Store and RLS tests** (`tests/integration/test_vector_store.py`, 20): filters of every type, typed matching, top-k under a strict filter, atomic replace, the deployment-wide count, and RLS at the database level with raw `SELECT`s and no `WHERE` clause: another workspace's rows are invisible, nothing is visible with no workspace set, writing into another workspace is refused, and the setting doesn't leak into the next transaction.
- **Cross-tenant tests generated from the route table** (`tests/integration/test_tenant_isolation.py`, 20). The test walks the app's routes, finds every one that depends on `get_principal`, and requires a case in `CASES` for each. Workspace A holds a secret; workspace B's key then lists, creates, uploads, deletes, searches, asks and streams, and each case checks B saw nothing and changed nothing of A's. A route added later without a case makes the suite fail. The same file checks that every data route answers 401 without a credential, and the role rules over sessions.

**A surprise in the route walk.** The first run found **no** routes, so the coverage check compared two empty sets and passed. FastAPI 0.141 keeps each included router as one `_IncludedRouter` entry (with the router under `.original_router`) instead of copying its routes into `app.routes`. The walk now recurses into them, and a separate test asserts that discovery finds known routes, so an empty discovery can't pass silently again.

### 21.6 The parity gate, and removing Chroma

`scripts/calibrate.py` now runs on `PgVectorStore` (in a throwaway workspace in the development database). Every score matched Chroma's to three decimals, for all 22 questions: top-1 13 of 14, and at `MIN_RELEVANCE = 0.58` with the prefix, all 14 answerable questions kept and all 8 unanswerable ones blocked. Both use exact cosine distance on the same vectors, so this was expected, but the plan required measuring it rather than assuming it.

Then `uv remove chromadb` took chromadb and its dependencies out, along with `CHROMA_PATH`, `COLLECTION_NAME` and the Chroma volume in Compose. The rebuilt stack started, `migrate` applied everything through `0005`, and `/documents` without a credential returned 401.

All 368 tests pass.

---

## How to run everything built so far

```bash
cd C:\dev\sourcely
uv sync                                                    # install exact locked versions
docker compose up -d db                                    # Postgres + pgvector (needed from Phase 1)
uv run alembic upgrade head                                # create or update the schema
cp .env.example .env                                       # then put your Gemini key in .env
uv run uvicorn app.main:create_app --factory --reload      # http://localhost:8000/docs
uv run pytest -q                                           # tests
uv run ruff check . && uv run ruff format --check .        # lint and format
uv run mypy                                                # types
```

`--reload` restarts the server when you save a file. Use it in development only.

Or, with Docker only (no local Python needed):

```bash
docker compose up --build        # http://localhost:8000/docs ; Ctrl+C or `docker compose down` to stop
docker compose down -v           # also delete the stored documents and the model cache
```

---

## Glossary

| Term | Meaning |
|---|---|
| **ASGI** | Asynchronous Server Gateway Interface: the contract between a Python web server (uvicorn) and a web app (FastAPI). The async successor to WSGI. |
| **Chunk** | A short piece of a document that gets its own embedding. |
| **Cosine similarity** | How closely two vectors point the same way: 1 means the same direction, 0 means unrelated. It's used to compare embeddings. |
| **Dependency injection** | A component receives what it needs from outside instead of creating it. FastAPI does this with `Depends`. |
| **Embedding** | A list of numbers (a vector) that represents a text's meaning. Similar meanings give nearby vectors. |
| **Fixture** | A pytest function that prepares an object a test needs. |
| **Lifespan** | FastAPI's startup and shutdown hook. |
| **Middleware** | Code that wraps every request and response. |
| **Pydantic model** | A class that declares a data shape and validates data against it. |
| **RAG** | Retrieval-Augmented Generation: find relevant text first, then give it to an LLM as context for the answer. |
| **Vector store** | A database built to find the vectors nearest to a query vector quickly. |
