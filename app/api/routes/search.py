"""Semantic search route."""

from fastapi import APIRouter

from app.api.deps import EmbedderDep, SettingsDep, StoreDep
from app.schemas.search import SearchFilters, SearchHit, SearchRequest, SearchResponse
from app.services.vector_store import Where, build_where

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest, settings: SettingsDep, embedder: EmbedderDep, store: StoreDep
) -> SearchResponse:
    """Return the stored chunks most similar in meaning to the query, with cosine scores."""
    top_k = body.top_k or settings.default_top_k
    hits = store.query(embedder.embed_query(body.query), top_k, where_from(body.filters))
    return SearchResponse(query=body.query, results=[SearchHit.from_chunk(hit) for hit in hits])


def where_from(filters: SearchFilters | None) -> Where | None:
    """The Chroma `where` clause for request filters, or None when there are none."""
    if filters is None:
        return None
    return build_where(filters.document_ids, filters.metadata)
