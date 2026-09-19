"""Semantic search route."""

from fastapi import APIRouter

from app.api.auth import IndexDep, PrincipalDep, require
from app.api.deps import EmbedderDep, SettingsDep
from app.schemas.search import SearchHit, SearchRequest, SearchResponse

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    principal: PrincipalDep,
    index: IndexDep,
) -> SearchResponse:
    """Return the workspace's chunks most similar in meaning to the query, with cosine scores."""
    require(principal, "read")
    top_k = body.top_k or settings.default_top_k
    search_filter = body.filters.to_filter() if body.filters else None
    hits = index.query(embedder.embed_query(body.query), top_k, search_filter)
    return SearchResponse(query=body.query, results=[SearchHit.from_chunk(hit) for hit in hits])
