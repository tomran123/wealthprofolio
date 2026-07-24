from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import LLMProviderConfig
from app.models.enums import LLMRole
from app.providers.llm.client import LLMClient

settings = get_settings()


def _fernet() -> Fernet:
    if not settings.llm_encryption_key:
        raise RuntimeError("llm_encryption_key_not_configured")
    try:
        return Fernet(settings.llm_encryption_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("llm_encryption_key_invalid") from exc


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("llm_api_key_decryption_failed") from exc


async def get_active_provider(db: AsyncSession, role: LLMRole) -> LLMProviderConfig | None:
    stmt = (
        select(LLMProviderConfig)
        .where(LLMProviderConfig.role == role, LLMProviderConfig.is_active.is_(True))
        .order_by(LLMProviderConfig.updated_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_active_client(db: AsyncSession, role: LLMRole) -> LLMClient:
    provider = await get_active_provider(db, role)
    if provider is None:
        raise RuntimeError(f"active_{role.value}_provider_not_configured")
    return LLMClient(
        api_key=decrypt_api_key(provider.api_key_encrypted),
        base_url=provider.base_url,
        model_name=provider.model_name,
    )
