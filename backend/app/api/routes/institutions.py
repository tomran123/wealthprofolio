import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.schemas.institution import InstitutionCreate, InstitutionRead, InstitutionUpdate
from app.services import institution_service

router = APIRouter(prefix="/api/institutions", tags=["institutions"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[InstitutionRead])
async def list_institutions(q: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    if q:
        return await institution_service.search_institutions(db, q)
    return await institution_service.list_institutions(db)


@router.post("", response_model=InstitutionRead, status_code=status.HTTP_201_CREATED)
async def create_institution(payload: InstitutionCreate, db: AsyncSession = Depends(get_db)):
    return await institution_service.create_institution(db, payload)


@router.patch("/{institution_id}", response_model=InstitutionRead)
async def update_institution(institution_id: uuid.UUID, payload: InstitutionUpdate, db: AsyncSession = Depends(get_db)):
    institution = await institution_service.update_institution(db, institution_id, payload)
    if institution is None:
        raise HTTPException(status_code=404, detail="institution_not_found")
    return institution


@router.delete("/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_institution(institution_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await institution_service.delete_institution(db, institution_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="institution_not_found")
