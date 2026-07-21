import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.exposure_group import ExposureGroupCreate, ExposureGroupRead, ExposureGroupUpdate
from app.services import exposure_group_service

router = APIRouter(prefix="/api/exposure-groups", tags=["exposure-groups"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ExposureGroupRead])
async def list_exposure_groups(db: AsyncSession = Depends(get_db)):
    return await exposure_group_service.list_exposure_groups(db)


@router.post("", response_model=ExposureGroupRead, status_code=status.HTTP_201_CREATED)
async def create_exposure_group(payload: ExposureGroupCreate, db: AsyncSession = Depends(get_db)):
    return await exposure_group_service.create_exposure_group(db, payload)


@router.patch("/{group_id}", response_model=ExposureGroupRead)
async def update_exposure_group(group_id: uuid.UUID, payload: ExposureGroupUpdate, db: AsyncSession = Depends(get_db)):
    group = await exposure_group_service.update_exposure_group(db, group_id, payload)
    if group is None:
        raise HTTPException(status_code=404, detail="exposure_group_not_found")
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exposure_group(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await exposure_group_service.delete_exposure_group(db, group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="exposure_group_not_found")
