# Build Log: how this project was built, step by step

This log records every step taken to build the RAG API, in order, with the commands that were run and the reasons behind them. It is written for someone who is new to FastAPI. Each step explains the framework or Python concept it relies on, so you can rebuild the project yourself and explain it in an interview.

- **What** we are building and the decisions that shape it: [`SPEC.md`](../SPEC.md)
- **The task order** and progress: [`tasks/plan.md`](../tasks/plan.md), [`tasks/todo.md`](../tasks/todo.md)
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
7. [How to run everything built so far](#how-to-run-everything-built-so-far)
8. [Glossary](#glossary)

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

    app = FastAPI(title="RAG API", lifespan=lifespan)
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

## How to run everything built so far

```bash
cd C:\dev\rag-api
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
