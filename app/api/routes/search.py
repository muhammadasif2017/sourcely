"""Semantic search route."""

from fastapi import APIRouter

from app.api.deps import EmbedderDep, SettingsDep, StoreDep
from app.schemas.search import SearchHit, SearchRequest, SearchResponse

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest, settings: SettingsDep, embedder: EmbedderDep, store: StoreDep
) -> SearchResponse:
    """Return the stored chunks most similar in meaning to the query, with cosine scores."""
    top_k = body.top_k or settings.default_top_k
    hits = store.query(embedder.embed_query(body.query), top_k)
    return SearchResponse(
        query=body.query,
        results=[
            SearchHit(
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                title=hit.title,
                text=hit.text,
                score=hit.score,
                metadata=hit.metadata,
            )
            for hit in hits
        ],
    )
