# Sourcely API image: two stages, so build tools and the uv cache stay out of the final image.

# --- build: install locked dependencies into a virtual environment -----------------------
FROM python:3.12-slim AS build

# uv is copied from its official image, pinned to the version the lockfile was made with.
COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /usr/local/bin/uv

# Compile bytecode now so the container starts faster; copy files out of the cache mount
# instead of linking to it, because the mount isn't part of the image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is rebuilt only when pyproject.toml or uv.lock change,
# not on every code edit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- runtime: the virtual environment plus the application code --------------------------
FROM python:3.12-slim AS runtime

# A fixed, unprivileged user. It owns only the data directory, the one place it writes.
RUN groupadd --system --gid 10001 sourcely \
    && useradd --system --uid 10001 --gid sourcely --no-create-home sourcely

WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY app ./app
# For the one-shot `migrate` service in docker-compose.yml.
COPY alembic.ini ./
COPY migrations ./migrations

# Named volumes mount here (see docker-compose.yml). Creating the directories as the
# sourcely user makes new volumes inherit that ownership.
RUN mkdir -p /app/data/models && chown -R sourcely:sourcely /app/data

# HF_HOME: the model download (Hugging Face, via fastembed) keeps its own cache under the
# user's home by default. This user has no home directory, so it goes in the model volume.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_CACHE_DIR=/app/data/models \
    HF_HOME=/app/data/models/.huggingface

USER sourcely

EXPOSE 8000

# The slim image has no curl, so the check uses Python's standard library. start-period
# covers the first start, when the embedding model (about 65 MB) is downloaded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
