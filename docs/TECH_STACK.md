# Tech Stack: what each technology is for and why it was chosen

This document justifies every technology in the project the way you would in a design review or an interview. For each one it covers:

- **What it is**
- **The problem it solves** in this project
- **Why we chose it**, with professional reasons
- **Main advantages** during development
- **Alternatives considered**, and why they lost
- **Limitations** you should know about and be able to admit
- **Where it's used** in the code

Versions are the ones locked in `uv.lock` on 2026-09-18.

Related docs: [`BUILD_LOG.md`](BUILD_LOG.md) (how it was built) and [`INTERVIEW_PREP.md`](INTERVIEW_PREP.md) (questions and answers).

---

## Summary

| Layer | Technology | One-line reason |
|---|---|---|
| Language | Python 3.12 | The AI/ML ecosystem lives in Python. 3.12 is the newest version all our native dependencies fully support. |
| Project and packages | uv | One fast tool for the Python version, virtualenv, dependencies and a lockfile, so installs are reproducible. |
| Web framework | FastAPI 0.141 | Type hints give validation, serialisation and OpenAPI docs for free. It's the standard for Python AI APIs. |
| ASGI server | Uvicorn 0.53 | The standard production server for FastAPI. |
| Data validation | Pydantic 2.13 | Declarative, fast (Rust core) validation of every request, response and setting. |
| Configuration | pydantic-settings 2.15 | Typed, validated config from env vars and `.env`, which fails fast at startup. |
| Vector database | ChromaDB 1.5 | Embedded vector store: no server, no key, persists to disk, filters on metadata. |
| Embeddings | fastembed 0.8 + ONNX Runtime | Local CPU embeddings without PyTorch. Free, offline, small install. |
| Embedding model | BAAI/bge-small-en-v1.5 | Strong retrieval quality for its size (384 dimensions), fast on CPU. |
| LLM (OpenAI-compatible) | openai SDK 3.15 | One client for OpenAI, Gemini and Ollama by changing `base_url`. |
| LLM (Claude) | anthropic SDK 1.6 | Official Claude client with typed errors, retries, streaming and refusal fallbacks. |
| Development LLM | Gemini `gemini-3.5-flash-lite` | Free tier, fast, good quality. Lets the project run end to end with no budget. |
| Testing | pytest 9.1 + httpx 0.28 (TestClient) | The Python testing standard. Tests the API in memory without a server. |
| Lint and format | Ruff 0.16 | One very fast tool replacing flake8, isort, pyupgrade and Black. |
| Type checking | mypy 2.3 (strict) | Catches type bugs before runtime. |
| Git hooks | pre-commit 4.6 | Runs the quality checks automatically before every commit. |
| CI | GitHub Actions | Runs lint, types and tests on every push and PR. |
| Packaging and deploy | Docker + Compose (Task 10) | Same runtime everywhere, one-command start. |
| File upload | python-multipart (Task 6) | Required by FastAPI to parse `multipart/form-data` uploads. |
| Streaming | Server-Sent Events (Task 9) | Simple one-way streaming of LLM tokens over plain HTTP. |

---

## 1. Python 3.12

**What it is.** The programming language, pinned to 3.12 in `.python-version`.

**Problem it solves.** We need a language with first-class libraries for embeddings, vector databases and LLM SDKs.

**Why chosen.**
- Python is the default language of AI/ML. Every vendor ships an official Python SDK first (OpenAI, Anthropic, Google), and most vector databases and embedding libraries are Python-first.
- **Version 3.12 specifically:** the machine's default Python is 3.14, but compiled dependencies (`onnxruntime` under `fastembed` and `chromadb`) publish pre-built wheels for mature versions first. 3.12 is fully supported, stable and still receiving security fixes. It also has modern typing syntax (`str | None`, `type` aliases) and faster startup than older versions.

**Advantages.** A huge ecosystem, fast prototyping, and readable code that non-specialists can review.

**Alternatives.**
- **Node.js/TypeScript:** good SDKs exist, but local embedding and ML tooling is weaker.
- **Go:** great for high-throughput services, but its AI ecosystem is thinner.

**Limitations.** Slower CPU-bound code than compiled languages, and the GIL limits CPU parallelism in threads. It doesn't matter here: the heavy work runs in native code (ONNX Runtime, Chroma's Rust core), and LLM calls are I/O-bound.

**Where used.** Everywhere. `requires-python = ">=3.12"` in `pyproject.toml`.

---

## 2. uv (package and project manager)

**What it is.** A Python package and project manager from Astral, written in Rust.

**Problem it solves.** Python projects traditionally juggle several tools: `pyenv` for Python versions, `venv` for isolation, `pip` for installs and `pip-tools` or Poetry for lockfiles. The result is slow installs and "works on my machine" version drift.

**Why chosen.**
- **Reproducibility:** `uv.lock` pins every package, including sub-dependencies, with hashes. `uv sync --locked` in CI and Docker installs exactly what was tested locally.
- **One tool:** `uv python pin`, `uv add`, `uv sync` and `uv run` cover the whole workflow.
- **Speed:** installs are much faster than pip, which matters in CI and Docker builds.
- **Consistency:** the sibling projects (`helpdesk-copilot`, `job-match-service`) already use uv.

**Advantages.** `uv run <cmd>` always runs inside the project's environment, with no "forgot to activate the venv" bugs. It uses the standard `pyproject.toml` (PEP 621), so there's no lock-in. Dev dependencies are separated (`[dependency-groups] dev`), so production images stay small.

**Alternatives.**
- **pip + requirements.txt:** no real lockfile for transitive dependencies, slow, and manual venv handling.
- **Poetry:** mature, but slower, and it uses its own resolver conventions.
- **conda:** heavy, and aimed at data science environments rather than web services.

**Limitations.** It's newer than pip, so some older tutorials don't mention it. Anyone can still install from `pyproject.toml` with pip.

**Where used.** `pyproject.toml`, `uv.lock`, `.python-version`, every command in the README, CI and the Dockerfile.

---

## 3. FastAPI (web framework)

**What it is.** A modern Python web framework for building APIs, built on Starlette (web layer) and Pydantic (data layer).

**Problem it solves.** We need HTTP endpoints that validate input, return consistent JSON, document themselves and are easy to test. Hand-writing validation and docs is slow and error-prone.

**Why chosen.**
- **Type hints drive everything.** Declaring `def search(body: SearchRequest)` gives automatic request parsing, validation (422 with field-level errors), serialisation and OpenAPI schema generation.
- **Automatic interactive docs** at `/docs` (Swagger UI) and `/redoc`. That's valuable for a PoC reviewed by a client: they can try every endpoint in a browser.
- **Built-in dependency injection** (`Depends`) keeps routes decoupled from how components are built, which makes testing with fakes trivial.
- **Sync and async support.** Plain `def` handlers run in a thread pool, so blocking libraries (Chroma, fastembed) are safe. Async and streaming are available where needed (SSE in Task 9).
- **Industry standard for Python AI backends.** Most LLM and RAG services and job postings use it, so reviewers and interviewers recognise the patterns.

**Advantages.** Very little boilerplate, excellent editor autocompletion thanks to types, first-class `TestClient`, lifespan hooks for loading models once, and high performance among Python frameworks.

**Alternatives.**
- **Flask:** simple and mature, but has no built-in validation, OpenAPI or DI. You'd bolt on marshmallow, flasgger and so on.
- **Django + DRF:** batteries-included (ORM, admin, auth), but heavy for a small API with no relational database.
- **Litestar:** similar ideas and fast, but a smaller community.

**Limitations.** Async mistakes are easy: a blocking call inside `async def` stalls the server, so we deliberately use `def`. There's no built-in auth or admin UI (not needed here).

**Where used.** `app/main.py` (app factory, lifespan), `app/api/routes/` (routers), `app/api/deps.py` (dependencies), `app/core/errors.py` (exception handlers).

---

## 4. Uvicorn (ASGI server)

**What it is.** A lightning-fast ASGI server. It accepts HTTP connections and hands requests to the FastAPI app.

**Problem it solves.** FastAPI is an *application*. It needs a *server* to listen on a port, parse HTTP and manage connections.

**Why chosen.** It's the server FastAPI documents and recommends. `uvicorn[standard]` adds `uvloop` (a faster event loop, on Linux) and `httptools` (a faster HTTP parser), plus `--reload` for development. It supports `--factory`, which fits our `create_app()` pattern.

**Advantages.** A single command to run (`uvicorn app.main:create_app --factory`), hot reload in development, and production-grade performance.

**Alternatives.**
- **Hypercorn:** supports HTTP/2 and HTTP/3, but is less common.
- **Gunicorn with Uvicorn workers:** the classic multi-process production setup. Recent Uvicorn has its own `--workers` flag, so it's rarely required.

**Limitations.** Serving TLS certificates and static files belongs behind a reverse proxy (nginx, a cloud load balancer) in production.

**Where used.** Dev command, README, Dockerfile `CMD`.

---

## 5. Pydantic v2 (data validation)

**What it is.** A data-validation library. You declare fields with types and constraints in a class, and it validates and converts incoming data.

**Problem it solves.** Every API must reject bad input (wrong types, empty text, oversized fields, invalid ids) and return consistent output. Without Pydantic, you'd write many manual `if` checks.

**Why chosen.**
- FastAPI is built on it, so request and response models get validation and OpenAPI docs automatically.
- **Declarative constraints** such as `Field(min_length=1, max_length=2000)`, `ge`/`le` ranges and regex `pattern` enforce the spec's limits in one readable place.
- **v2 has a Rust core** (`pydantic-core`), so validation is fast.
- `response_model` filters output, preventing accidental data leaks.

**Advantages.** Validation, parsing, serialisation and docs come from a single definition. Errors are precise and machine-readable (422 with field paths). The mypy plugin type-checks model usage.

**Alternatives.**
- **dataclasses + manual checks:** no validation.
- **marshmallow:** older, more verbose, and not native to FastAPI.
- **attrs + cattrs:** good, but not integrated with FastAPI.

**Limitations.** Complex cross-field rules need validators, and migration between major versions (v1 to v2) was a breaking change industry-wide.

**Where used.** `app/schemas/` (all request and response models), `app/core/config.py` (settings).

---

## 6. pydantic-settings (configuration)

**What it is.** A Pydantic extension that loads settings from environment variables and `.env` files into a typed class.

**Problem it solves.** Configuration (API keys, model names, chunk sizes, paths) must live outside the code (a Twelve-Factor App principle), must be validated, and must be easy to change per environment: local, Docker, CI.

**Why chosen.**
- **Type conversion and validation at startup.** `CHUNK_SIZE=abc` or `LLM_PROVIDER=cohere` fails immediately with a clear message, instead of breaking on the first request.
- **Cross-field rules** (`chunk_overlap < chunk_size`) are enforced in a `model_validator`.
- **One source of truth.** The class itself documents every option, its type and its default.
- **Environment-variable precedence** lets Docker and CI override `.env` without code changes.
- It's the same library the sibling project `job-match-service` uses.

**Advantages.** Secrets stay in `.env` (gitignored) with `.env.example` as the template. Tests build `Settings(...)` directly with `_env_file=None`, so a developer's local `.env` can't leak into tests.

**Alternatives.**
- **`os.getenv` scattered through the code:** untyped, unvalidated, undiscoverable.
- **python-dotenv alone:** loads the file but doesn't validate.
- **Dynaconf or Hydra:** powerful, but heavier than needed.

**Limitations.** It isn't a secrets manager. In production, inject secrets from a vault or the platform's secret store as environment variables.

**Where used.** `app/core/config.py`, `.env.example`.

---

## 7. ChromaDB (vector database)

**What it is.** An open-source vector database (Apache-2.0). It stores embeddings with their text and metadata, and finds the nearest vectors to a query.

**Problem it solves.** Semantic search means finding the chunks whose embeddings are closest to the query embedding. Doing this by brute force in Python doesn't scale and has no persistence or filtering.

**Why chosen.**
- **Embedded mode.** `PersistentClient(path=...)` runs inside our process and saves to `data/chroma`, like SQLite. It needs no separate server, no Docker for the database, and no account or API key. That's ideal for a PoC and keeps setup to `uv sync`.
- **The task names it** ("ChromaDB or Qdrant"), so reviewers expect one of the two.
- **Cosine distance with an HNSW index** (approximate nearest-neighbour search), configured with `{"hnsw": {"space": "cosine"}}`.
- **Metadata filtering** (`where` with `$eq`, `$in`, `$and`) powers the search filters in Task 8 without another system.
- **Upgrade path.** The same client API works against Chroma running as a server, for when the API scales to several replicas.

**Advantages.** Minimal setup, persistence across restarts, and in-memory `EphemeralClient` for fast isolated tests. It stores documents and metadata next to vectors, so there's no second database. We pass our own vectors (`embedding_function=None`), which keeps the embedding choice independent of the store.

**Alternatives.**
- **Qdrant:** excellent performance and filtering, and strong at scale. Its local mode exists, but server mode (Docker) is its main path, which is more setup than needed for the PoC.
- **pgvector:** best when Postgres is already in the stack. It isn't here.
- **FAISS:** a fast library, but not a database: no metadata, no persistence API, no filtering.
- **Pinecone and other managed services:** need an account and a key and cost money at scale. The project has no budget.

**Limitations.** Embedded mode is single-process: multiple API replicas can't safely share one local folder. At large scale and high write concurrency, a server deployment (Chroma server, Qdrant) is needed. `GET /documents` has to scan chunk metadata because Chroma has no "documents" table.

**Where used.** `app/services/vector_store.py`, created in the lifespan in `app/main.py`.

---

## 8. fastembed + ONNX Runtime (local embeddings)

**What it is.** A lightweight embedding library from Qdrant. It runs embedding models through ONNX Runtime, an optimised inference engine for exported models, on the CPU.

**Problem it solves.** Every document chunk and every query needs an embedding. Hosted embedding APIs cost money and need a key. Claude has no embeddings API at all.

**Why chosen.**
- **Free and offline.** No key and no per-request cost. Ingest and search keep working even if the LLM provider is down or out of quota.
- **No PyTorch.** `sentence-transformers` pulls in PyTorch (hundreds of MB to GBs). fastembed uses ONNX Runtime, so the install and the Docker image stay much smaller, and CPU inference is fast.
- **Separate query and passage entry points** (`query_embed()` and `embed()`). Models that need a query prefix get it without changing our code. For bge-small-en-v1.5, we verified that both return the same vector, meaning no prefix is added. Whether adding bge's optional instruction helps is measured at Checkpoint B.
- **Decoupled from the LLM choice.** Switching between Gemini, OpenAI and Claude never forces re-embedding stored documents.
- It's the same library `helpdesk-copilot` already uses.

**Advantages.** The model downloads once (about 65 MB, cached in `data/models`), then loads in seconds at startup. Behaviour is deterministic, and nothing leaves the machine during embedding.

**Alternatives.**
- **OpenAI `text-embedding-3-small`:** high quality and cheap, but needs a paid key and a network call for every ingest and query.
- **sentence-transformers:** the most flexible, but brings the PyTorch dependency weight.
- **Gemini embeddings:** would work, but would spend free-tier quota on every search.
- **Chroma's built-in default embedder:** hides the model choice inside the store. We want it explicit and swappable.

**Limitations.** CPU-bound, so very large ingests are slower than a GPU or a hosted API. The small model is less accurate than large hosted models on some domains. Changing the model later means re-embedding every document.

**Where used.** `app/services/embeddings.py` (`FastEmbedEmbedder`, behind the `Embedder` protocol).

---

## 9. BAAI/bge-small-en-v1.5 (embedding model)

**What it is.** A small English text-embedding model from the Beijing Academy of Artificial Intelligence (BAAI). It outputs 384-dimensional vectors.

**Why chosen.** It's fastembed's default and a well-known strong performer for retrieval at its size, fast on CPU, with a small download. 384 dimensions keep storage and search cheap compared with 768- or 1536-dimension models.

**Limitations.** English-focused. For multilingual documents, choose a multilingual model (for example a multilingual E5 or bge-m3 variant). Its similarity scores for unrelated text are not near zero, which is why `MIN_RELEVANCE` is calibrated from measured data.

**Where used.** `EMBEDDING_MODEL` in settings.

---

## 10. openai Python SDK (OpenAI-compatible LLMs)

**What it is.** OpenAI's official Python client.

**Problem it solves.** We need to call a chat model reliably: authentication, retries, timeouts, typed responses, streaming and typed errors.

**Why chosen.**
- **Official and maintained:** correct request shapes, built-in retries with backoff on 429 and 5xx, timeouts, and typed exceptions (`RateLimitError`, `AuthenticationError`, `APITimeoutError`) that map cleanly to our HTTP errors.
- **One client, many providers.** Google Gemini, Ollama, Groq and others expose OpenAI-compatible endpoints. Setting `OPENAI_BASE_URL` points the same code at any of them. That's how the project runs free on Gemini now and on real OpenAI for a client later, with zero code changes.

**Advantages.** It avoids hand-written HTTP code, and streaming support is built in (Task 9).

**Alternatives.**
- **Raw `httpx` requests:** you re-implement retries, errors and streaming parsing.
- **LangChain or LlamaIndex:** large abstractions with frequent breaking changes. Too heavy for two chat calls, and they hide what's happening, which is bad for learning and debugging.
- **LiteLLM:** a good multi-provider router, but an extra dependency when two small classes suffice.

**Limitations.** "OpenAI-compatible" providers differ in edge cases (streaming chunk shapes, supported parameters), so each provider must be verified live. Gemini's model names change over time: `gemini-2.5-*` already returns 404 for new users.

**Where used.** `app/services/llm.py` (`OpenAICompatibleLLM`, Task 5).

---

## 11. anthropic Python SDK (Claude)

**What it is.** Anthropic's official Python client for Claude.

**Why chosen.**
- The task explicitly allows Claude, so the service supports it as a first-class provider.
- The official SDK gives typed errors, retries, timeouts, streaming (`messages.stream`), and access to beta features such as **server-side refusal fallbacks** (`fallbacks="default"`), which re-run a declined request on a fallback model.
- The default model is `claude-opus-5`, Anthropic's current recommended default.

**Why not route Claude through the OpenAI SDK?** Anthropic's native API has its own request shape (a top-level `system` field, typed content blocks, `stop_reason` values such as `refusal`) and features that compatibility layers don't expose. The official SDK is the correct, supported path.

**Limitations.** It can't be verified live without an `ANTHROPIC_API_KEY`. The code is written against the installed SDK's verified signatures and unit-tested with a fake client, and the README says so.

**Where used.** `app/services/llm.py` (`AnthropicLLM`, Task 5).

---

## 12. Google Gemini, free tier (development LLM)

**What it is.** Google's LLM family, reached through its OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`).

**Why chosen.** The developer has no paid OpenAI or Anthropic credit. Gemini's free tier gives a daily request quota at zero cost, which is enough for development, tests and demos. `gemini-3.5-flash-lite` was verified live (answered in 1.6s) and is pinned by exact name rather than a `-latest` alias, so results stay reproducible.

**Limitations.**
- **Rate limits and daily quotas:** a 429 maps to our 503.
- **Model retirements:** watch Google's deprecation notices.
- **Privacy:** on the free tier, Google may use prompts and responses to improve its products. Don't ingest confidential text with a free-tier key. This is documented in `.env.example`.

**Offline alternative:** Ollama (`qwen2.5:3b`) runs locally with no quota and no data leaving the machine. It's slower on CPU and lower quality.

---

## 13. pytest + httpx (TestClient)

**What it is.** pytest is Python's de facto testing framework. FastAPI's `TestClient` (built on httpx) sends HTTP requests to the app in memory.

**Problem it solves.** We need fast, repeatable proof that every endpoint, validation rule and error path behaves as the spec says, without a running server or paid API calls.

**Why chosen.**
- **pytest:** plain `assert`, **fixtures** for setup (`client`, `store`, `embedder` in `conftest.py`), `parametrize` for many cases in one test, and a huge plugin ecosystem.
- **TestClient:** exercises the real routing, validation, middleware and exception handlers, which amounts to an integration test in milliseconds. Using it as a context manager also runs the lifespan.

**Advantages.** The full suite runs in under a second. Fakes (a hashed bag-of-words embedder, in-memory Chroma, a fake LLM) make tests deterministic and free.

**Alternatives.** `unittest` from the standard library is more verbose (class-based, `self.assertEqual`) and has no fixtures of pytest's kind.

**Limitations.** Fakes prove *our* logic, not provider behaviour, so the plan includes a manual live check against the real model and Gemini.

**Where used.** `tests/` and `[tool.pytest.ini_options]` in `pyproject.toml`.

---

## 14. Ruff (lint and format)

**What it is.** An extremely fast Python linter and formatter from Astral (the makers of uv), written in Rust.

**Problem it solves.** It keeps code consistent and catches likely bugs (unused imports, undefined names, mutable default arguments, outdated syntax) automatically, so code review can focus on logic.

**Why chosen.** One tool replaces flake8, isort, pyupgrade and Black, with one config block in `pyproject.toml` and near-instant runs. Rule sets enabled: `E` and `F` (pycodestyle and pyflakes errors), `I` (import sorting), `UP` (modern syntax), and `B` (bugbear, likely bugs). It's the same configuration as `job-match-service`.

**Alternatives.** Black + isort + flake8 means three tools, three configs, and slower runs.

**Where used.** `[tool.ruff]` in `pyproject.toml`, the pre-commit hook and CI.

---

## 15. mypy, strict mode (static type checking)

**What it is.** A static type checker that reads the type hints and reports mismatches without running the code.

**Problem it solves.** Type bugs, such as passing `None` where a `str` is required or returning the wrong type, would otherwise appear only at runtime, possibly in production.

**Why chosen.**
- The spec promises "type hints everywhere", and mypy *enforces* that promise. Ruff doesn't check types.
- **Strict mode** requires annotations on every function and flags `Any` leaking in.
- The **pydantic plugin** understands Pydantic models and settings.

It has already caught a real issue: a function declared to return `list[float]` was returning an untyped value from fastembed.

**Alternatives.** Pyright is faster and powers VS Code's Pylance. It's equally valid. mypy is the long-standing reference implementation.

**Limitations.** Third-party libraries without type hints (fastembed, parts of chromadb) need `ignore_missing_imports`, so checking stops at those boundaries.

**Where used.** `[tool.mypy]` in `pyproject.toml`, the pre-commit hook and CI.

---

## 16. pre-commit (git hooks)

**What it is.** A framework that runs configured checks automatically on `git commit`.

**Problem it solves.** Developers forget to run the linters. Bad formatting, broken types or an accidentally committed secret reach the repository.

**Why chosen.** Checks run on every commit and block it on failure. Hooks: trailing whitespace, end-of-file, YAML and TOML syntax, large files, merge-conflict markers, **private-key detection**, ruff, ruff-format and mypy. The ruff and mypy hooks run through `uv run`, so they use exactly the versions in `uv.lock`, the same as CI.

**Advantages.** Feedback in seconds before code is shared, and a consistent history.

**Where used.** `.pre-commit-config.yaml`. Install once with `uv run pre-commit install`.

---

## 17. GitHub Actions (continuous integration)

**What it is.** GitHub's built-in CI/CD service.

**Problem it solves.** It guarantees that every push and pull request passes lint, types and tests on a clean machine, independent of any developer's setup.

**Why chosen.** It's free for public repos, lives next to the code, and is what the sibling projects use. `astral-sh/setup-uv` with caching makes installs fast, and `uv sync --locked` fails the build if the lockfile is out of date.

**Where used.** `.github/workflows/ci.yml`.

---

## 18. Docker + Docker Compose (Task 10)

**What it is.** Containers package the app together with its exact Python version and system libraries. Compose starts it with its configuration and volumes in one command.

**Problem it solves.** "Works on my machine." Anyone, including a client, a reviewer or a server, can run `docker compose up --build` and get the same runtime.

**Why chosen.** It's the industry-standard deployment unit. The planned setup:
- `python:3.12-slim` base image, with dependencies installed from `uv.lock` without dev tools, so the image is small.
- A non-root user and a healthcheck on `/health`.
- Volumes for `data/` (the Chroma data and the embedding model cache), so data and the downloaded model survive restarts and rebuilds.

**Limitations.** The image is sizeable because of ONNX Runtime. Embedded Chroma still means one container. Scaling out needs a shared vector store server.

---

## 19. python-multipart (Task 6)

**What it is.** A parser for `multipart/form-data`, the encoding browsers and `curl -F` use for file uploads.

**Why chosen.** FastAPI requires it for any endpoint that accepts `UploadFile` or `Form` fields. We need it for `POST /documents/upload`. There's no real alternative: it's FastAPI's documented dependency for form data.

**Where used.** `app/api/routes/documents.py` (`upload_document`, Task 6), through FastAPI's `UploadFile`, `File` and `Form`. Version 0.0.32.

**Limits.** Starlette spools the uploaded file to a temporary file before the route runs, so the whole upload is received even if the route then rejects it. The route caps how much it *reads*, but the request body size itself should be capped in front of the app (the reverse proxy or container in Task 10).

---

## 19b. Docker and Compose (Task 10)

**What it is.** Docker packages the app, its Python and its libraries into an *image* that runs the same way on any machine. Compose describes how to run it: ports, configuration and storage volumes.

**Why chosen.** One command (`docker compose up --build`) replaces installing Python 3.12, uv and the dependencies, and it's what most hosting platforms run.

**Where used.** `Dockerfile`, `docker-compose.yml` and `.dockerignore`.

- **Two stages.** The build stage copies uv from its official image (pinned to 0.9.22) and runs `uv sync --frozen --no-dev --no-install-project` with a cache mount. The runtime stage copies only the virtual environment and `app/`, so uv and its cache aren't in the final image.
- **Dependencies before code.** `pyproject.toml` and `uv.lock` are copied and installed before `app/`, so editing code reuses the cached dependency layer.
- **Non-root user** `sourcely` (uid 10001). It owns only `/app/data`.
- **Named volumes** `chroma-data` and `model-cache`, so the index and the 65 MB embedding model survive restarts and rebuilds.
- **Health check** in Python's standard library, because the slim image has no curl, with a 120-second start period for the first model download.

**Limitations.** The image is about 840 MB, mostly onnxruntime and chromadb. Embedded Chroma still means one container: several replicas would need a shared vector store. There's no TLS; a reverse proxy would provide it in production.

---

## 20. Server-Sent Events (Task 9)

**What it is.** A standard (`text/event-stream`) for a server to push a stream of events over a normal HTTP response.

**Problem it solves.** LLM answers take seconds. Streaming tokens as they're generated makes the service feel responsive, which is the "typing" effect in chat UIs.

**Why chosen over WebSockets.** The data flows only one way (server to client). SSE works over plain HTTP, through proxies and with `curl -N`, and needs no extra library: FastAPI's `StreamingResponse` is enough. WebSockets are for two-way, long-lived conversations, which is more complexity than needed.

**Where used.** `POST /ask/stream` in `app/api/routes/ask.py` (Task 9), fed by `start_answer_stream` in `app/services/rag.py` and each adapter's `stream()` in `app/services/llm.py`.

**Limitation.** Browsers' built-in `EventSource` only sends `GET`, and `/ask/stream` is a `POST` with a JSON body. A browser client reads the response with `fetch` and a `ReadableStream` instead. The product plan's web app does exactly that.

---

## 21. PostgreSQL with pgvector (Phase 1, from Task 12)

**What it is.** PostgreSQL is a relational database. pgvector is an extension that adds a `vector` column type, distance operators such as cosine distance (`<=>`) and approximate nearest-neighbour indexes (HNSW).

**Problem it solves.** Phase 1 needs users, sessions, workspaces and keys (relational data with constraints) and tenant isolation that holds even if code forgets a filter. Postgres gives transactions, foreign keys and **row-level security**. pgvector lets the vectors live in the same database, so deleting a document and its vectors is one transaction.

**Why chosen over keeping Chroma plus a separate database.** Two stores can disagree after a crash, need two backups, and row-level security can't cover Chroma. Decision D3 in `docs/product/ARCHITECTURE.md` has the full comparison.

**Where used.** The `db` service in `docker-compose.yml` (`pgvector/pgvector:pg17`, host port 5434), the CI service container, and the per-run test database.

**Limitations.** Tests now need a running Postgres. pgvector's HNSW index is approximate, like Chroma's, and holds its graph in memory.

---

## 22. SQLAlchemy 2, psycopg 3 and Alembic (Phase 1, from Task 12)

**What they are.** SQLAlchemy is Python's standard database toolkit: typed table classes and a query builder. psycopg 3 is the PostgreSQL driver underneath it. Alembic writes and applies versioned schema *migrations* for SQLAlchemy.

**Why chosen.** SQLAlchemy 2's typed API works with mypy strict. The sync engine fits the existing `def` routes, which FastAPI already runs in a threadpool, so no async rewrite is needed. psycopg 3 is the maintained driver (psycopg2 is in maintenance), and its binary package needs no compiler. Alembic is SQLAlchemy's own migration tool; the alternative, creating tables at startup, can't evolve a schema that already holds data.

**Where used.** `app/db/` (base, engine, models), `DbDep` in `app/api/deps.py` (one session and transaction per request), `alembic.ini` and `migrations/`. Migrations connect as `sourcely_owner`; the app connects as `sourcely_app`.

**Details worth knowing.**

- A **naming convention** on the metadata gives every index and constraint a predictable name, so later migrations can refer to them.
- `pool_pre_ping=True` checks a pooled connection before using it, replacing ones the server dropped.
- `connect_timeout=5` bounds how long a request waits for an unreachable database.

Also added in Task 12, and explained when first used: `pgvector` (Python package, Task 16), `argon2-cffi` and `email-validator` (Task 13).

---

## 23. argon2-cffi and email-validator (Phase 1, Task 13)

**argon2-cffi** hashes passwords with **Argon2id**, the winner of the Password Hashing Competition and the first recommendation of the OWASP password storage guidance. It's deliberately slow and memory-hungry, so an attacker with a stolen database can try far fewer guesses per second than with a fast hash such as SHA-256. Each hash includes a random salt and its own parameters (`$argon2id$v=19$m=...`), so parameters can be raised later without breaking old hashes. The library's defaults follow RFC 9106.

**Why not bcrypt?** Still acceptable, but it limits passwords to 72 bytes and isn't memory-hard. Argon2id is the current first choice.

**Tokens use SHA-256, not Argon2.** Session, email and invite tokens are 32 random bytes, so there's nothing to guess; a fast hash only has to stop a stolen row from being usable. Passwords are chosen by people and can be guessed, which is what the slow hash is for.

**email-validator** is what Pydantic's `EmailStr` uses to check an address's syntax. It rejects malformed addresses at the edge (422) without sending anything.

**Where used.** `app/core/security.py` (hashing, tokens, the common-password list), `app/schemas/auth.py` (`EmailStr`, password rules), `app/services/accounts.py`.

---

## Architecture choices that aren't packages

These are patterns, not libraries, but interviewers ask about them:

| Choice | Problem it solves | Advantage |
|---|---|---|
| **Layered layout** (`api/`, `core/`, `schemas/`, `services/`) | Mixed concerns make code hard to test and change | Thin routes, testable services, familiar structure for reviewers |
| **App factory** (`create_app`) | A module-level app reads config and loads models on import | Isolated test apps with fakes, and no import side effects |
| **Dependency injection** (`Depends`) | Routes that construct their own components can't be tested with fakes | Swap real or fake components without touching routes |
| **`Protocol` interfaces** (`Embedder`) | Tight coupling to one library | Any object with the right methods fits, and mypy verifies it |
| **Request-id middleware** | Impossible to trace one failing request through the logs | Every log line and response carries `X-Request-ID` |
| **Central error mapping** (`AppError`, handlers) | Inconsistent error responses and leaked internals | Predictable status codes, and no stack traces sent to clients |
| **Spec-driven development and TDD** | Silent wrong assumptions and untested code | Decisions are written down, and behaviour is proven by tests |
