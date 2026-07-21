from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

BASE_CURRENCY_KEY = "base_currency"


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    setting = await db.get(AppSetting, key)
    return setting.value if setting is not None else default


async def set_setting(db: AsyncSession, key: str, value: str) -> AppSetting:
    setting = await db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    await db.commit()
    await db.refresh(setting)
    return setting


async def get_base_currency(db: AsyncSession, default: str) -> str:
    return await get_setting(db, BASE_CURRENCY_KEY, default) or default
