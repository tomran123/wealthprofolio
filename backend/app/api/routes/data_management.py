import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ImportBatch
from app.schemas.import_batch import ImportBatchRead
from app.core.config import get_settings
from app.services import data_export_service, database_backup_service, import_service

router = APIRouter(prefix="/api/data", tags=["data-management"], dependencies=[Depends(get_current_user)])

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
settings = get_settings()


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


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/csv")
async def export_csv(db: AsyncSession = Depends(get_db)):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    content = await data_export_service.export_csv_zip_bytes(db)
    return _download(content, "application/zip", f"wealthportfolio_csv_{stamp}.zip")


@router.get("/export/json")
async def export_json(db: AsyncSession = Depends(get_db)):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    content = await data_export_service.export_json_bytes(db)
    return _download(content, "application/json", f"wealthportfolio_{stamp}.json")


@router.get("/backup/download")
async def download_database_backup():
    try:
        content = await database_backup_service.create_sql_backup()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return _download(content, "application/sql", f"wealthportfolio_backup_{stamp}.sql")


@router.post("/backup/restore")
async def restore_database_backup(
    confirmation: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if confirmation != "RESTORE":
        raise HTTPException(status_code=400, detail="restore_confirmation_required")
    if not file.filename:
        raise HTTPException(status_code=400, detail="restore_filename_required")
    content = await file.read()
    if len(content) > settings.backup_max_bytes:
        raise HTTPException(status_code=400, detail="database_backup_too_large")
    try:
        if file.filename.lower().endswith(".json"):
            restored = await data_export_service.restore_json_bytes(db, content)
            return {"ok": True, "format": "json", "restored": restored}
        if file.filename.lower().endswith(".sql"):
            # Authentication already ran; release its read transaction before a
            # separate psql process takes schema locks for the restore.
            await db.rollback()
            await database_backup_service.restore_sql_backup(content)
            return {"ok": True, "format": "sql"}
        raise HTTPException(status_code=400, detail="unsupported_backup_type")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
