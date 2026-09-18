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
16. [How to run everything built so far](#how-to-run-everything-built-so-far)
17. [Glossary](#glossary)

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

## How to run everything built so far

```bash
cd C:\dev\sourcely
uv sync                                                    # install exact locked versions
cp .env.example .env                                       # then put your Gemini key in .env
uv run uvicorn app.main:create_app --factory --reload      # http://localhost:8000/docs
uv run pytest -q                                           # tests
uv run ruff check . && uv run ruff format --check .        # lint and format
uv run mypy                                                # types
```

`--reload` restarts the server when you save a file. Use it in development only.

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
