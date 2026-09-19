"""FastAPI dependencies that hand routes the components stored on `app.state`."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.embeddings import Embedder
from app.services.llm import LLM
from app.services.vector_store import PgVectorStore


def get_settings(request: Request) -> Settings:
    """Settings the app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_embedder(request: Request) -> Embedder:
    """The embedding model."""
    embedder: Embedder = request.app.state.embedder
    return embedder


def get_store(request: Request) -> PgVectorStore:
    """The vector store."""
    store: PgVectorStore = request.app.state.store
    return store


def get_engine(request: Request) -> Engine:
    """The database connection pool."""
    engine: Engine = request.app.state.engine
    return engine


def get_db(request: Request) -> Iterator[Session]:
    """One database session and transaction per request.

    The transaction commits when the route returns normally and rolls back if it raises.
    """
    with Session(get_engine(request)) as session, session.begin():
        yield session


def get_llm(request: Request) -> LLM | None:
    """The configured LLM, or None when its API key is missing (routes answer 503)."""
    llm: LLM | None = request.app.state.llm
    return llm


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
StoreDep = Annotated[PgVectorStore, Depends(get_store)]
LLMDep = Annotated[LLM | None, Depends(get_llm)]
EngineDep = Annotated[Engine, Depends(get_engine)]
DbDep = Annotated[Session, Depends(get_db)]
