import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ImportBatch
from app.schemas.import_batch import ImportBatchRead
from app.services import import_service

router = APIRouter(prefix="/api/data", tags=["data-management"], dependencies=[Depends(get_current_user)])

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _to_schema(batch: ImportBatch) -> ImportBatchRead:
    rows = batch.parsed_rows.get("rows", [])
    status_value = batch.status.value if hasattr(batch.status, "value") else batch.status
    return ImportBatchRead(
        id=batch.id,
        filename=batch.filename,
        status=status_value,
        row_count=batch.row_count,
        matched_count=batch.matched_count,
        created_count=batch.created_count,
        error_count=batch.error_count,
        rows=rows,
    )


@router.get("/import/template", response_class=PlainTextResponse)
async def download_template() -> PlainTextResponse:
    return PlainTextResponse(
        content=import_service.generate_template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wealthportfolio_import_template.csv"},
    )


@router.post("/import", response_model=ImportBatchRead)
async def preview_import(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="unsupported_file_type")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="file_too_large")
    batch = await import_service.parse_and_preview(db, file.filename, content)
    return _to_schema(batch)


@router.post("/import/{batch_id}/commit", response_model=ImportBatchRead)
async def commit_import(batch_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        batch = await import_service.commit_batch(db, batch_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="batch_not_found") from None
    return _to_schema(batch)
