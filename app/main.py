"""Application factory.

Run with: `uvicorn app.main:create_app --factory`. There is deliberately no module-level
`app`, so importing this module (e.g. from tests) never reads `.env` or loads models.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import chromadb
from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.services.embeddings import Embedder, FastEmbedEmbedder
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> FastAPI:
    """Build the app. Components not passed in are created from settings at startup."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.embedder = embedder or FastEmbedEmbedder(
            settings.embedding_model, settings.embedding_cache_dir
        )
        app.state.store = store or VectorStore(
            chromadb.PersistentClient(path=settings.chroma_path), settings.collection_name
        )
        logger.info(
            "ready: embedding_model=%s llm=%s/%s configured=%s",
            settings.embedding_model,
            settings.llm_provider,
            settings.llm_model,
            settings.llm_configured,
        )
        yield

    app = FastAPI(
        title="RAG API",
        version="0.1.0",
        summary="Ingest text, search it semantically and answer questions from it with an LLM.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app
