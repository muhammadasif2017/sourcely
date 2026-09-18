"""Document ingestion routes."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import EmbedderDep, SettingsDep, StoreDep
from app.core.errors import AppError
from app.schemas.documents import DocumentCreate, DocumentCreated
from app.services.chunking import chunk_text

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=DocumentCreated, status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate, settings: SettingsDep, embedder: EmbedderDep, store: StoreDep
) -> DocumentCreated:
    """Chunk, embed and store a text document. Re-using an id replaces that document."""
    characters = len(body.text)
    if characters > settings.max_document_chars:
        raise AppError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Document is {characters} characters; the limit is {settings.max_document_chars}",
        )
    document_id = body.document_id or str(uuid.uuid4())
    title = body.title or ""
    chunks = chunk_text(body.text, settings.chunk_size, settings.chunk_overlap)
    # Embed before touching the store, so a failure here keeps the previous version intact.
    embeddings = embedder.embed_documents(chunks)
    store.replace_document(document_id, chunks, embeddings, body.metadata, title)
    return DocumentCreated(
        document_id=document_id, title=title, chunks=len(chunks), characters=characters
    )
