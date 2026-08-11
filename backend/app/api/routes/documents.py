import uuid
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi import (
    status as http_status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_request_context
from app.core.config import get_settings
from app.core.family_scope import family_scoped_get
from app.models.document import Document, DocumentPage
from app.schemas.document import (
    DocumentCompleteRequest,
    DocumentCompleteResult,
    DocumentContentReceipt,
    DocumentDetail,
    DocumentPageResult,
    DocumentReprocessResult,
    DocumentTransactionDraft,
    DocumentUploadIntent,
    DocumentUploadIntentCreate,
    DocumentUploadTarget,
)
from app.services import document_draft_service, document_service
from app.services.document_pipeline_service import enqueue_document_job
from app.storage import get_object_storage

router = APIRouter(
    prefix="/api/v1/documents",
    tags=["documents"],
    dependencies=[Depends(get_request_context)],
)
settings = get_settings()


def _document_error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail == "document_too_large":
        code = 413
    elif detail in {
        "unsupported_document_type",
        "document_extension_mime_mismatch",
        "document_magic_mime_mismatch",
        "unrecognized_document_magic",
    }:
        code = 415
    elif detail.endswith("_not_found"):
        code = 404
    elif detail in {
        "invalid_upload_token",
        "upload_token_expired",
    }:
        code = 403
    elif detail in {
        "document_not_ready",
        "document_upload_incomplete",
        "document_not_awaiting_upload",
        "transaction_draft_not_pending",
        "transaction_draft_has_no_items",
    } or detail.startswith("draft_item_"):
        code = 409
    elif isinstance(exc, RuntimeError):
        code = 503
    else:
        code = 400
    return HTTPException(status_code=code, detail=detail)


@router.post("/upload-intents", response_model=DocumentUploadIntent)
async def create_upload_intent(
    payload: DocumentUploadIntentCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        document, version, token, presigned, duplicate = (
            await document_service.create_upload_intent(db, payload)
        )
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    upload = None
    if not duplicate and token:
        if presigned is not None:
            upload = DocumentUploadTarget(
                method="PUT",
                url=presigned.url,
                headers=presigned.headers,
                expires_at=presigned.expires_at,
            )
        else:
            upload = DocumentUploadTarget(
                method="PUT",
                url=f"/api/v1/documents/{document.id}/content",
                headers={
                    "Content-Type": version.content_type,
                    "X-Upload-Token": token,
                },
                expires_at=version.upload_token_expires_at,
            )
    return DocumentUploadIntent(
        document_id=document.id,
        version_id=version.id,
        status=document.status,
        duplicate=duplicate,
        upload=upload,
        upload_token=token,
    )


@router.put("/{document_id}/content", response_model=DocumentContentReceipt)
async def upload_content(
    document_id: uuid.UUID,
    request: Request,
    upload_token: str | None = Header(default=None, alias="X-Upload-Token"),
    content_length: int | None = Header(default=None, alias="Content-Length"),
    db: AsyncSession = Depends(get_db),
):
    if content_length is not None and content_length > settings.document_max_file_bytes:
        raise HTTPException(status_code=413, detail="document_too_large")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > settings.document_max_file_bytes:
            raise HTTPException(status_code=413, detail="document_too_large")
    try:
        document, version, inspection = await document_service.put_document_content(
            db,
            document_id,
            upload_token,
            bytes(content),
        )
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return DocumentContentReceipt(
        document_id=document.id,
        version_id=version.id,
        received_bytes=len(content),
        sha256=inspection.sha256,
    )


@router.get("/{document_id}/content")
async def download_content(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    if document.status in ("pending_upload", "uploading"):
        raise HTTPException(status_code=409, detail="document_upload_incomplete")
    if document.status == "failed":
        raise HTTPException(status_code=409, detail="document_content_unavailable")
    try:
        content = await get_object_storage(document.storage_backend).get_bytes(
            document.storage_key
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document_content_not_found") from exc
    encoded_name = quote(document.filename, safe="")
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": (
                f"attachment; filename=\"document\"; filename*=UTF-8''{encoded_name}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{document_id}/complete",
    response_model=DocumentCompleteResult,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def complete_upload(
    document_id: uuid.UUID,
    payload: DocumentCompleteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    try:
        document, job, skip_enqueue = await document_service.complete_upload(
            db,
            document_id,
            payload,
        )
        if not skip_enqueue and job.status in ("pending", "queued", "failed"):
            enqueue_document_job(background_tasks, job)
        summary = await document_service.document_summary_schema(db, document)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return DocumentCompleteResult(
        document=summary,
        job=document_service.job_schema(job),
    )


@router.get("", response_model=DocumentPageResult)
async def list_documents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await document_service.list_documents(
        db,
        offset=offset,
        limit=limit,
        status=status,
        document_type=type,
    )
    items = [await document_service.document_summary_schema(db, row) for row in rows]
    return DocumentPageResult(items=items, total=total, offset=offset, limit=limit)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    document = await document_service.get_document_detail(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    return await document_service.document_detail_schema(db, document)


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentReprocessResult,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def reprocess_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    try:
        _, job = await document_service.create_reprocess_job(db, document_id)
        enqueue_document_job(background_tasks, job)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return DocumentReprocessResult(job=document_service.job_schema(job))


@router.get("/{document_id}/pages/{page_number}/preview")
async def preview_page(
    document_id: uuid.UUID,
    page_number: int,
    db: AsyncSession = Depends(get_db),
):
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    page = (
        await db.execute(
            select(DocumentPage).where(
                DocumentPage.document_id == document.id,
                DocumentPage.page_number == page_number,
            )
        )
    ).scalar_one_or_none()
    if page is None or not page.preview_storage_key:
        raise HTTPException(status_code=404, detail="document_page_preview_not_found")
    try:
        content = await get_object_storage(document.storage_backend).get_bytes(
            page.preview_storage_key
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document_page_preview_not_found") from exc
    return Response(
        content=content,
        media_type=page.preview_content_type or "image/png",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Disposition": f'inline; filename="page-{page_number}.png"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{document_id}/transaction-drafts",
    response_model=DocumentTransactionDraft,
)
async def get_transaction_draft(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    draft = await document_draft_service.latest_transaction_draft(db, document.id)
    if draft is None:
        raise HTTPException(status_code=404, detail="transaction_draft_not_found")
    return document_draft_service.draft_schema(draft)


@router.post(
    "/{document_id}/transaction-drafts",
    response_model=DocumentTransactionDraft,
)
async def create_transaction_draft(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        draft = await document_draft_service.create_transaction_draft(db, document_id)
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return document_draft_service.draft_schema(draft)


@router.post(
    "/{document_id}/transaction-drafts/{draft_id}/confirm",
    response_model=DocumentTransactionDraft,
)
async def confirm_transaction_draft(
    document_id: uuid.UUID,
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        draft = await document_draft_service.confirm_transaction_draft(
            db,
            document_id,
            draft_id,
        )
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return document_draft_service.draft_schema(draft)


@router.post(
    "/{document_id}/transaction-drafts/{draft_id}/cancel",
    response_model=DocumentTransactionDraft,
)
async def cancel_transaction_draft(
    document_id: uuid.UUID,
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        draft = await document_draft_service.cancel_transaction_draft(
            db,
            document_id,
            draft_id,
        )
    except (ValueError, RuntimeError) as exc:
        await db.rollback()
        raise _document_error(exc) from exc
    return document_draft_service.draft_schema(draft)
