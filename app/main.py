"""Application factory.

Run with: `uvicorn app.main:create_app --factory`. There is deliberately no module-level
`app`, so importing this module (e.g. from tests) never reads `.env` or loads models.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import chromadb
from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.middleware import RequestContextMiddleware, RequestSizeLimitMiddleware
from app.api.routes import ask, auth, documents, health, search, workspaces
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.engine import make_engine
from app.services.email import EmailSender, create_email_sender
from app.services.embeddings import Embedder, FastEmbedEmbedder
from app.services.llm import LLM, create_llm
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    llm: LLM | None = None,
    engine: Engine | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    """Build the app. Components not passed in are created from settings at startup."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = engine or make_engine(settings.database_url)
        app.state.email_sender = email_sender or create_email_sender(settings)
        app.state.embedder = embedder or FastEmbedEmbedder(
            settings.embedding_model,
            settings.embedding_cache_dir,
            settings.embedding_query_prefix,
        )
        app.state.store = store or VectorStore(
            chromadb.PersistentClient(path=settings.chroma_path), settings.collection_name
        )
        _check_embedding_dim(app.state.embedder, settings.embedding_dim)
        # None when the provider's key is missing: /ask answers 503, the rest keeps working.
        app.state.llm = llm if llm is not None else create_llm(settings)
        logger.info(
            "ready: embedding_model=%s llm=%s/%s configured=%s",
            settings.embedding_model,
            settings.llm_provider,
            settings.llm_model,
            settings.llm_configured,
        )
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="Sourcely",
        version="0.1.0",
        summary="Ingest text, search it semantically and answer questions from it with an LLM.",
        lifespan=lifespan,
    )
    # The last middleware added runs first, so the request id also covers 413 responses.
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(ask.router)
    return app


def _check_embedding_dim(embedder: Embedder, expected: int) -> None:
    """Fail at startup if the model's vectors don't fit the database's vector column."""
    actual = len(embedder.embed_query("dimension check"))
    if actual != expected:
        raise RuntimeError(
            f"EMBEDDING_DIM is {expected}, but the embedding model returns {actual}-dimension "
            "vectors. Set EMBEDDING_DIM to match the model (and migrate the vector column)."
        )
