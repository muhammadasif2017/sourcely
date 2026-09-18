"""Document ingestion routes: JSON text and file upload."""

import uuid
from pathlib import PureWindowsPath
from typing import Annotated

from fastapi import APIRouter, File, Form, Path, Response, UploadFile, status

from app.api.deps import EmbedderDep, SettingsDep, StoreDep
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.documents import (
    DOCUMENT_ID_PATTERN,
    MAX_TITLE_CHARS,
    DocumentCreate,
    DocumentCreated,
    DocumentList,
    DocumentSummary,
)
from app.services.embeddings import Embedder
from app.services.ingestion import ingest_text
from app.services.vector_store import Metadata, VectorStore

router = APIRouter(tags=["documents"])

UPLOAD_EXTENSIONS = (".txt", ".md")
# A UTF-8 character is at most 4 bytes, so a file within the character limit is never larger.
_MAX_BYTES_PER_CHAR = 4


@router.post("/documents", response_model=DocumentCreated, status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate, settings: SettingsDep, embedder: EmbedderDep, store: StoreDep
) -> DocumentCreated:
    """Chunk, embed and store a text document. Re-using an id replaces that document."""
    return _ingest(
        body.text, body.document_id, body.title or "", body.metadata, settings, embedder, store
    )


@router.get("/documents", response_model=DocumentList)
def list_documents(store: StoreDep) -> DocumentList:
    """List stored documents with their title, chunk count and metadata, sorted by id."""
    return DocumentList(
        documents=[
            DocumentSummary(
                document_id=doc.document_id,
                title=doc.title,
                chunks=doc.chunks,
                metadata=doc.metadata,
            )
            for doc in store.list_documents()
        ]
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: Annotated[str, Path(pattern=DOCUMENT_ID_PATTERN)], store: StoreDep
) -> Response:
    """Delete a document and all its chunks, so it no longer appears in search or answers."""
    if not store.delete_document(document_id):
        raise AppError(status.HTTP_404_NOT_FOUND, f"Document '{document_id}' not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/documents/upload", response_model=DocumentCreated, status_code=status.HTTP_201_CREATED
)
def upload_document(
    file: Annotated[UploadFile, File(description="A UTF-8 `.txt` or `.md` file")],
    settings: SettingsDep,
    embedder: EmbedderDep,
    store: StoreDep,
    document_id: Annotated[str | None, Form(pattern=DOCUMENT_ID_PATTERN)] = None,
) -> DocumentCreated:
    """Ingest a `.txt` or `.md` file. The file name becomes the title."""
    # PureWindowsPath splits on both "\\" and "/", so any client-side path is dropped.
    filename = PureWindowsPath(file.filename or "").name
    if not filename.lower().endswith(UPLOAD_EXTENSIONS):
        raise AppError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .txt and .md files are supported"
        )
    # Read at most one byte past the largest size that could still be within the limit, so an
    # oversized upload is never held in memory whole.
    max_bytes = settings.max_document_chars * _MAX_BYTES_PER_CHAR
    raw = file.file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise _too_large(settings)
    try:
        # utf-8-sig also removes a byte order mark, which some Windows editors add.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "File must be UTF-8 encoded text"
        ) from exc
    if not text.strip():
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "File must contain non-whitespace characters"
        )
    return _ingest(text, document_id, filename[:MAX_TITLE_CHARS], {}, settings, embedder, store)


def _ingest(
    text: str,
    document_id: str | None,
    title: str,
    metadata: Metadata,
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
) -> DocumentCreated:
    """Apply the size limit, then store the document under the given or a generated id."""
    characters = len(text)
    if characters > settings.max_document_chars:
        raise _too_large(settings, characters)
    document_id = document_id or str(uuid.uuid4())
    chunks = ingest_text(
        document_id,
        text,
        title,
        metadata,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embedder=embedder,
        store=store,
    )
    return DocumentCreated(
        document_id=document_id, title=title, chunks=chunks, characters=characters
    )


def _too_large(settings: Settings, characters: int | None = None) -> AppError:
    size = f"Document is {characters} characters; the" if characters else "The"
    return AppError(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"{size} limit is {settings.max_document_chars} characters",
    )
