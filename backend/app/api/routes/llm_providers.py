import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_family_admin
from app.models import LLMProviderConfig
from app.schemas.llm_provider import LLMProviderCreate, LLMProviderRead, LLMProviderUpdate
from app.services import llm_provider_service

router = APIRouter(
    prefix="/api/settings/llm-providers",
    tags=["llm-providers"],
    dependencies=[Depends(require_family_admin)],
)


def _to_schema(provider: LLMProviderConfig) -> LLMProviderRead:
    return LLMProviderRead(
        id=provider.id,
        name=provider.name,
        provider_key=provider.provider_key,
        role=provider.role,
        base_url=provider.base_url,
        model_name=provider.model_name,
        is_active=provider.is_active,
        has_api_key=bool(provider.api_key_encrypted),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.get("", response_model=list[LLMProviderRead])
async def list_providers(db: AsyncSession = Depends(get_db)):
    return [_to_schema(row) for row in await llm_provider_service.list_providers(db)]


@router.post("", response_model=LLMProviderRead, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: LLMProviderCreate, db: AsyncSession = Depends(get_db)):
    try:
        return _to_schema(await llm_provider_service.create_provider(db, payload))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{provider_id}", response_model=LLMProviderRead)
async def update_provider(
    provider_id: uuid.UUID, payload: LLMProviderUpdate, db: AsyncSession = Depends(get_db)
):
    try:
        provider = await llm_provider_service.update_provider(db, provider_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider is None:
        raise HTTPException(status_code=404, detail="llm_provider_not_found")
    return _to_schema(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if not await llm_provider_service.delete_provider(db, provider_id):
        raise HTTPException(status_code=404, detail="llm_provider_not_found")
