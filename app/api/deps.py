"""FastAPI dependencies that hand routes the components stored on `app.state`."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.embeddings import Embedder
from app.services.vector_store import VectorStore


def get_settings(request: Request) -> Settings:
    """Settings the app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_embedder(request: Request) -> Embedder:
    """The embedding model."""
    embedder: Embedder = request.app.state.embedder
    return embedder


def get_store(request: Request) -> VectorStore:
    """The vector store."""
    store: VectorStore = request.app.state.store
    return store


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
StoreDep = Annotated[VectorStore, Depends(get_store)]
