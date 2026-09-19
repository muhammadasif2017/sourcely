"""Turning a document's text into stored chunks. Shared by the JSON and file-upload routes."""

from app.services.chunking import chunk_text
from app.services.embeddings import Embedder
from app.services.vector_store import Metadata, WorkspaceIndex


def ingest_text(
    document_id: str,
    text: str,
    title: str,
    metadata: Metadata,
    *,
    chunk_size: int,
    chunk_overlap: int,
    embedder: Embedder,
    index: WorkspaceIndex,
) -> int:
    """Chunk, embed and store `text`, replacing any earlier version. Returns the chunk count."""
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    # Embed before touching the store, so a failure here keeps the previous version intact.
    embeddings = embedder.embed_documents(chunks)
    index.replace_document(document_id, chunks, embeddings, metadata, title)
    return len(chunks)
