import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMProviderConfig
from app.models.enums import LLMRole
from app.providers.llm.registry import encrypt_api_key
from app.schemas.llm_provider import LLMProviderCreate, LLMProviderUpdate

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "minimax": "https://api.minimax.chat/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "seed": "https://ark.cn-beijing.volces.com/api/v3",
}


async def list_providers(db: AsyncSession) -> list[LLMProviderConfig]:
    stmt = select(LLMProviderConfig).order_by(LLMProviderConfig.role, LLMProviderConfig.name)
    return list((await db.execute(stmt)).scalars().all())


async def _deactivate_role(db: AsyncSession, role: LLMRole, except_id: uuid.UUID | None = None) -> None:
    stmt = update(LLMProviderConfig).where(LLMProviderConfig.role == role)
    if except_id:
        stmt = stmt.where(LLMProviderConfig.id != except_id)
    await db.execute(stmt.values(is_active=False))


async def create_provider(db: AsyncSession, data: LLMProviderCreate) -> LLMProviderConfig:
    provider_key = data.provider_key.lower()
    base_url = data.base_url or DEFAULT_BASE_URLS.get(provider_key)
    if not base_url:
        raise ValueError("base_url_required_for_custom_provider")
    provider = LLMProviderConfig(
        name=data.name,
        provider_key=provider_key,
        role=data.role,
        base_url=base_url.rstrip("/"),
        api_key_encrypted=encrypt_api_key(data.api_key),
        model_name=data.model_name,
        is_active=data.is_active,
    )
    try:
        db.add(provider)
        await db.flush()
        if provider.is_active:
            await _deactivate_role(db, provider.role, provider.id)
        await db.commit()
        await db.refresh(provider)
        return provider
    except Exception:
        await db.rollback()
        raise


async def update_provider(
    db: AsyncSession, provider_id: uuid.UUID, data: LLMProviderUpdate
) -> LLMProviderConfig | None:
    provider = await db.get(LLMProviderConfig, provider_id)
    if provider is None:
        return None
    values = data.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    if api_key:
        provider.api_key_encrypted = encrypt_api_key(api_key)
    for field, value in values.items():
        if field == "base_url" and value:
            value = value.rstrip("/")
        if field == "provider_key" and value:
            value = value.lower()
        setattr(provider, field, value)
    if provider.is_active:
        await _deactivate_role(db, provider.role, provider.id)
    await db.commit()
    await db.refresh(provider)
    return provider


async def delete_provider(db: AsyncSession, provider_id: uuid.UUID) -> bool:
    provider = await db.get(LLMProviderConfig, provider_id)
    if provider is None:
        return False
    await db.delete(provider)
    await db.commit()
    return True
