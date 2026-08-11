from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_request_context
from app.schemas.document import (
    KnowledgeQueryRequest,
    KnowledgeQueryResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from app.services import knowledge_service

router = APIRouter(
    prefix="/api/v1/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(get_request_context)],
)


@router.post("/search", response_model=KnowledgeSearchResult)
async def search(
    payload: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    return await knowledge_service.search_knowledge(db, payload.query, payload)


@router.post("/query", response_model=KnowledgeQueryResult)
async def query(
    payload: KnowledgeQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    return await knowledge_service.query_knowledge(db, payload.question, payload)
