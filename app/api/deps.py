"""FastAPI dependencies that hand routes the components stored on `app.state`."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.embeddings import Embedder
from app.services.llm import LLM
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


def get_llm(request: Request) -> LLM | None:
    """The configured LLM, or None when its API key is missing (routes answer 503)."""
    llm: LLM | None = request.app.state.llm
    return llm


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
StoreDep = Annotated[VectorStore, Depends(get_store)]
LLMDep = Annotated[LLM | None, Depends(get_llm)]
