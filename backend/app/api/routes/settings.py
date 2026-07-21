from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(get_current_user)])
settings = get_settings()


@router.get("", response_model=AppSettingsRead)
async def get_app_settings(db: AsyncSession = Depends(get_db)):
    base_currency = await settings_service.get_base_currency(db, settings.default_base_currency)
    return AppSettingsRead(base_currency=base_currency)


@router.put("", response_model=AppSettingsRead)
async def update_app_settings(payload: AppSettingsUpdate, db: AsyncSession = Depends(get_db)):
    await settings_service.set_setting(db, settings_service.BASE_CURRENCY_KEY, payload.base_currency.upper())
    return AppSettingsRead(base_currency=payload.base_currency.upper())
