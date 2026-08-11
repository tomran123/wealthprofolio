from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_scope import require_bound_family_id
from app.models import AppSetting

BASE_CURRENCY_KEY = "base_currency"


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    family_id = require_bound_family_id(db)
    setting = (
        await db.execute(
            select(AppSetting).where(
                AppSetting.family_id == family_id,
                AppSetting.key == key,
            )
        )
    ).scalar_one_or_none()
    return setting.value if setting is not None else default


async def set_setting(
    db: AsyncSession,
    key: str,
    value: str,
    *,
    commit: bool = True,
) -> AppSetting:
    family_id = require_bound_family_id(db)
    setting = (
        await db.execute(
            select(AppSetting)
            .where(
                AppSetting.family_id == family_id,
                AppSetting.key == key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if setting is None:
        setting = AppSetting(family_id=family_id, key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    if commit:
        await db.commit()
        await db.refresh(setting)
    else:
        await db.flush()
    return setting


async def get_base_currency(db: AsyncSession, default: str) -> str:
    return await get_setting(db, BASE_CURRENCY_KEY, default) or default
