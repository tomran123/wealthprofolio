import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.owner import OwnerCreate, OwnerRead, OwnerUpdate
from app.services import owner_service

router = APIRouter(prefix="/api/owners", tags=["owners"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[OwnerRead])
async def list_owners(q: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    if q:
        return await owner_service.search_owners(db, q)
    return await owner_service.list_owners(db)


@router.post("", response_model=OwnerRead, status_code=status.HTTP_201_CREATED)
async def create_owner(payload: OwnerCreate, db: AsyncSession = Depends(get_db)):
    return await owner_service.create_owner(db, payload)


@router.patch("/{owner_id}", response_model=OwnerRead)
async def update_owner(owner_id: uuid.UUID, payload: OwnerUpdate, db: AsyncSession = Depends(get_db)):
    owner = await owner_service.update_owner(db, owner_id, payload)
    if owner is None:
        raise HTTPException(status_code=404, detail="owner_not_found")
    return owner


@router.delete("/{owner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_owner(owner_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await owner_service.delete_owner(db, owner_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="owner_not_found")
