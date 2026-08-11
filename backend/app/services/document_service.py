import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.family_scope import (
    family_scoped_get,
    get_bound_request_context,
    require_bound_family_id,
)
from app.models import Account, Institution, Owner
from app.models.document import (
    BackgroundJob,
    Document,
    DocumentExtraction,
    DocumentVersion,
)
from app.schemas.document import (
    BackgroundJobRead,
    DocumentCompleteRequest,
    DocumentDetail,
    DocumentExtractedField,
    DocumentExtractionRead,
    DocumentPageRead,
    DocumentSummary,
    DocumentUploadIntentCreate,
)
from app.services.document_security_service import (
    DocumentInspection,
    inspect_document_content,
    validate_upload_metadata,
)
from app.storage import ObjectStorage, PresignedUpload, get_object_storage

settings = get_settings()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _lock_family_hash(
    db: AsyncSession,
    family_id: uuid.UUID,
    digest: str,
) -> None:
    lock_bytes = hashlib.sha256(f"{family_id}:{digest}".encode("ascii")).digest()[:8]
    lock_id = int.from_bytes(lock_bytes, "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_id)))


def _verify_upload_token(version: DocumentVersion, token: str | None) -> None:
    if not token or not version.upload_token_hash:
        raise ValueError("invalid_upload_token")
    expires_at = version.upload_token_expires_at
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise ValueError("upload_token_expired")
    if not hmac.compare_digest(version.upload_token_hash, _token_hash(token)):
        raise ValueError("invalid_upload_token")


async def _validate_relationships(
    db: AsyncSession,
    data: DocumentUploadIntentCreate,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    owner = (
        await family_scoped_get(db, Owner, data.owner_id) if data.owner_id is not None else None
    )
    if data.owner_id is not None and owner is None:
        raise ValueError("owner_not_found")
    institution = (
        await family_scoped_get(db, Institution, data.institution_id)
        if data.institution_id is not None
        else None
    )
    if data.institution_id is not None and institution is None:
        raise ValueError("institution_not_found")
    account = (
        await family_scoped_get(db, Account, data.account_id)
        if data.account_id is not None
        else None
    )
    if data.account_id is not None and account is None:
        raise ValueError("account_not_found")
    if account is not None:
        if data.owner_id is not None and account.owner_id != data.owner_id:
            raise ValueError("document_account_owner_mismatch")
        if data.institution_id is not None and account.institution_id != data.institution_id:
            raise ValueError("document_account_institution_mismatch")
        return data.owner_id or account.owner_id, data.institution_id or account.institution_id
    return data.owner_id, data.institution_id


async def current_version(db: AsyncSession, document: Document) -> DocumentVersion:
    version = (
        await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version_number == document.current_version_number,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise RuntimeError("document_version_not_found")
    return version


async def create_upload_intent(
    db: AsyncSession,
    data: DocumentUploadIntentCreate,
) -> tuple[Document, DocumentVersion, str | None, PresignedUpload | None, bool]:
    filename, content_type = validate_upload_metadata(
        data.filename,
        data.content_type,
        data.size_bytes,
        data.sha256,
    )
    if len(json.dumps(data.metadata, ensure_ascii=False, default=str).encode("utf-8")) > 64 * 1024:
        raise ValueError("document_metadata_too_large")
    owner_id, institution_id = await _validate_relationships(db, data)
    family_id = require_bound_family_id(db)

    if data.sha256:
        await _lock_family_hash(db, family_id, data.sha256)
        duplicate = (
            await db.execute(
                select(Document).where(
                    Document.sha256 == data.sha256,
                    Document.status.notin_(("failed", "archived")),
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return duplicate, await current_version(db, duplicate), None, None, True
        resumable = (
            await db.execute(
                select(Document, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(
                    DocumentVersion.expected_sha256 == data.sha256,
                    Document.status.in_(("pending_upload", "uploading", "uploaded")),
                    DocumentVersion.version_number == Document.current_version_number,
                )
                .order_by(Document.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if resumable is not None:
            document, version = resumable
            token = secrets.token_urlsafe(32)
            version.upload_token_hash = _token_hash(token)
            version.upload_token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=settings.document_upload_intent_seconds
            )
            storage = get_object_storage(version.storage_backend)
            presigned = await storage.presign_upload(
                version.storage_key,
                version.content_type,
                settings.document_upload_intent_seconds,
            )
            await db.commit()
            return document, version, token, presigned, False

    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    version_number = 1
    storage = get_object_storage()
    storage_key = (
        f"families/{family_id}/documents/{document_id}/"
        f"versions/{version_number}/source"
    )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.document_upload_intent_seconds
    )
    context = get_bound_request_context(db)
    document = Document(
        id=document_id,
        family_id=family_id,
        filename=filename,
        content_type=content_type,
        size_bytes=data.size_bytes,
        sha256=None,
        document_type=data.document_type,
        document_date=data.document_date,
        status="pending_upload",
        page_count=0,
        current_version_number=version_number,
        storage_backend=storage.name,
        storage_key=storage_key,
        owner_id=owner_id,
        institution_id=institution_id,
        account_id=data.account_id,
        created_by_user_id=context.user_id if context else None,
        metadata_json=data.metadata,
    )
    version = DocumentVersion(
        id=version_id,
        family_id=family_id,
        document_id=document_id,
        version_number=version_number,
        status="pending_upload",
        content_type=content_type,
        size_bytes=data.size_bytes,
        expected_sha256=data.sha256,
        storage_backend=storage.name,
        storage_key=storage_key,
        upload_token_hash=_token_hash(token),
        upload_token_expires_at=expires_at,
        created_by_user_id=context.user_id if context else None,
        metadata_json={},
    )
    db.add_all([document, version])
    await db.flush()
    presigned = await storage.presign_upload(
        storage_key,
        content_type,
        settings.document_upload_intent_seconds,
    )
    await db.commit()
    return document, version, token, presigned, False


async def put_document_content(
    db: AsyncSession,
    document_id: uuid.UUID,
    upload_token: str | None,
    content: bytes,
) -> tuple[Document, DocumentVersion, DocumentInspection]:
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise ValueError("document_not_found")
    version = await current_version(db, document)
    if version.expected_sha256:
        await _lock_family_hash(db, document.family_id, version.expected_sha256)
    _verify_upload_token(version, upload_token)
    if document.status not in ("pending_upload", "uploading", "uploaded"):
        raise ValueError("document_not_awaiting_upload")
    inspection = await inspect_document_content(
        content,
        version.content_type,
        expected_size=version.size_bytes,
        expected_sha256=version.expected_sha256,
    )
    storage = get_object_storage(version.storage_backend)
    await storage.put_bytes(version.storage_key, content, version.content_type)
    version.actual_sha256 = inspection.sha256
    version.status = "uploaded"
    version.metadata_json = {
        **(version.metadata_json or {}),
        "security_warnings": list(inspection.warnings),
    }
    document.page_count = inspection.page_count
    document.status = "uploaded"
    document.error = None
    await db.commit()
    return document, version, inspection


async def _inspect_stored_version(
    version: DocumentVersion,
    storage: ObjectStorage,
) -> DocumentInspection:
    info = await storage.stat(version.storage_key)
    if info.size_bytes != version.size_bytes:
        raise ValueError("document_size_mismatch")
    content = await storage.get_bytes(version.storage_key)
    return await inspect_document_content(
        content,
        version.content_type,
        expected_size=version.size_bytes,
        expected_sha256=version.expected_sha256,
    )


async def latest_job_for_document(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> BackgroundJob | None:
    return (
        await db.execute(
            select(BackgroundJob)
            .where(
                BackgroundJob.resource_type == "document",
                BackgroundJob.resource_id == document_id,
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def complete_upload(
    db: AsyncSession,
    document_id: uuid.UUID,
    request: DocumentCompleteRequest,
) -> tuple[Document, BackgroundJob, bool]:
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise ValueError("document_not_found")
    version = await current_version(db, document)
    await _lock_family_hash(
        db,
        document.family_id,
        version.expected_sha256 or f"document:{document.id}",
    )
    await db.refresh(document)
    await db.refresh(version)

    if document.status in ("ready", "queued", "processing"):
        if request.sha256 and document.sha256 != request.sha256:
            raise ValueError("document_sha256_mismatch")
        existing_job = await latest_job_for_document(db, document.id)
        if existing_job is None:
            enqueue_existing = document.status == "queued"
            existing_job = BackgroundJob(
                job_type="document.process",
                status="succeeded" if document.status == "ready" else "queued",
                stage="completed" if document.status == "ready" else "queued",
                progress=100 if document.status == "ready" else 0,
                message="Duplicate document reused",
                result_json={"document_id": str(document.id), "deduplicated": True},
                resource_type="document",
                resource_id=document.id,
                created_by_user_id=document.created_by_user_id,
            )
            db.add(existing_job)
            await db.commit()
        else:
            enqueue_existing = (
                document.status == "queued"
                and existing_job.status in ("pending", "queued", "failed")
            )
        # A previous broker publish can fail after the durable job commit. A
        # repeated complete request must retry the publish instead of leaving a
        # document permanently queued. Duplicate deliveries are safe because
        # the worker claims the row and checks its heartbeat.
        return document, existing_job, not enqueue_existing

    _verify_upload_token(version, request.upload_token)
    storage = get_object_storage(version.storage_backend)
    try:
        inspection = await _inspect_stored_version(version, storage)
    except Exception as exc:
        # Direct-to-object-store uploads are untrusted until complete. Invalid
        # or malicious bytes are removed immediately and can never be previewed.
        delete_failed = False
        try:
            await storage.delete(version.storage_key)
        except Exception:
            delete_failed = True
        version.status = "failed"
        version.upload_token_hash = None
        version.upload_token_expires_at = None
        version.metadata_json = {
            **(version.metadata_json or {}),
            "quarantine_delete_failed": delete_failed,
        }
        document.status = "failed"
        document.error = f"{type(exc).__name__}: {exc}"[:1000]
        await db.commit()
        raise
    if request.sha256 and inspection.sha256 != request.sha256:
        raise ValueError("document_sha256_mismatch")

    # Hashes are optional at intent creation, so two uploads can discover that
    # they are identical only after the object has been inspected. Serialize
    # that discovery and reuse the already-live document instead of surfacing a
    # unique-index race to the client.
    await _lock_family_hash(db, document.family_id, inspection.sha256)
    duplicate_document = (
        await db.execute(
            select(Document)
            .where(
                Document.id != document.id,
                Document.sha256 == inspection.sha256,
                Document.status.notin_(("failed", "archived")),
            )
            .order_by(Document.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if duplicate_document is not None:
        delete_failed = False
        try:
            await storage.delete(version.storage_key)
        except Exception:
            delete_failed = True
        version.actual_sha256 = inspection.sha256
        version.status = "archived"
        version.upload_token_hash = None
        version.upload_token_expires_at = None
        document.status = "archived"
        document.metadata_json = {
            **(document.metadata_json or {}),
            "duplicate_of": str(duplicate_document.id),
            "duplicate_source_delete_failed": delete_failed,
        }
        existing_job = await latest_job_for_document(db, duplicate_document.id)
        enqueue_existing = False
        if existing_job is None:
            enqueue_existing = duplicate_document.status != "ready"
            duplicate_version = await current_version(db, duplicate_document)
            existing_job = BackgroundJob(
                job_type="document.process",
                status="queued" if enqueue_existing else "succeeded",
                stage="queued" if enqueue_existing else "completed",
                progress=0 if enqueue_existing else 100,
                message="Duplicate document reused",
                result_json={
                    "document_id": str(duplicate_document.id),
                    "deduplicated": True,
                },
                input_json={
                    "document_id": str(duplicate_document.id),
                    "document_version_id": str(duplicate_version.id),
                },
                resource_type="document",
                resource_id=duplicate_document.id,
                created_by_user_id=duplicate_document.created_by_user_id,
            )
            db.add(existing_job)
        await db.commit()
        return duplicate_document, existing_job, not enqueue_existing

    version.actual_sha256 = inspection.sha256
    version.status = "uploaded"
    version.upload_token_hash = None
    version.upload_token_expires_at = None
    version.metadata_json = {
        **(version.metadata_json or {}),
        "security_warnings": list(inspection.warnings),
    }
    document.sha256 = inspection.sha256
    document.page_count = inspection.page_count
    document.status = "queued"
    document.error = None
    context = get_bound_request_context(db)
    job = BackgroundJob(
        job_type="document.process",
        status="queued",
        stage="queued",
        progress=0,
        message="Document queued for processing",
        input_json={
            "document_id": str(document.id),
            "document_version_id": str(version.id),
        },
        resource_type="document",
        resource_id=document.id,
        created_by_user_id=context.user_id if context else document.created_by_user_id,
    )
    db.add(job)
    await db.commit()
    return document, job, False


async def create_reprocess_job(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> tuple[Document, BackgroundJob]:
    document = await family_scoped_get(db, Document, document_id)
    if document is None:
        raise ValueError("document_not_found")
    if document.status in ("pending_upload", "uploading"):
        raise ValueError("document_upload_incomplete")
    version = await current_version(db, document)
    storage = get_object_storage(version.storage_backend)
    await storage.stat(version.storage_key)
    context = get_bound_request_context(db)
    document.status = "queued"
    document.error = None
    job = BackgroundJob(
        job_type="document.reprocess",
        status="queued",
        stage="queued",
        progress=0,
        message="Document queued for reprocessing",
        input_json={
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "reprocess": True,
        },
        resource_type="document",
        resource_id=document.id,
        created_by_user_id=context.user_id if context else document.created_by_user_id,
    )
    db.add(job)
    await db.commit()
    return document, job


async def list_documents(
    db: AsyncSession,
    *,
    offset: int,
    limit: int,
    status: str | None,
    document_type: str | None,
) -> tuple[list[Document], int]:
    conditions = []
    if status:
        conditions.append(Document.status == status)
    if document_type:
        conditions.append(Document.document_type == document_type)
    total = int(
        (
            await db.execute(select(func.count()).select_from(Document).where(*conditions))
        ).scalar_one()
    )
    rows = list(
        (
            await db.execute(
                select(Document)
                .where(*conditions)
                .order_by(Document.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return rows, total


async def get_document_detail(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return (
        await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .options(
                selectinload(Document.pages),
                selectinload(Document.extractions),
            )
        )
    ).scalar_one_or_none()


async def get_job(db: AsyncSession, job_id: uuid.UUID) -> BackgroundJob | None:
    return await family_scoped_get(db, BackgroundJob, job_id)


def job_schema(job: BackgroundJob) -> BackgroundJobRead:
    return BackgroundJobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        stage=job.stage,
        progress=max(0, min(100, job.progress)),
        message=job.message,
        error=job.error,
        result=job.result_json,
        resource_type=job.resource_type,
        resource_id=job.resource_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def document_summary_schema(db: AsyncSession, document: Document) -> DocumentSummary:
    latest_job = await latest_job_for_document(db, document.id)
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        document_type=document.document_type,
        document_date=document.document_date,
        status=document.status,
        page_count=document.page_count,
        owner_id=document.owner_id,
        institution_id=document.institution_id,
        account_id=document.account_id,
        latest_job_id=latest_job.id if latest_job else None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _extraction_fields(extraction: DocumentExtraction) -> list[DocumentExtractedField]:
    fields = extraction.data_json.get("fields", []) if extraction.data_json else []
    result: list[DocumentExtractedField] = []
    for field in fields:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        try:
            result.append(DocumentExtractedField.model_validate(field))
        except ValidationError:
            continue
    return result


async def document_detail_schema(db: AsyncSession, document: Document) -> DocumentDetail:
    summary = await document_summary_schema(db, document)
    pages = sorted(document.pages, key=lambda item: item.page_number)
    extractions = sorted(document.extractions, key=lambda item: item.created_at, reverse=True)
    return DocumentDetail(
        **summary.model_dump(),
        sha256=document.sha256 or "",
        metadata=document.metadata_json or {},
        pages=[
            DocumentPageRead(
                id=page.id,
                page_number=page.page_number,
                status=page.status,
                text_preview=(
                    " ".join((page.extracted_text or "").split())[:500] or None
                ),
                ocr_confidence=page.ocr_confidence,
                preview_url=(
                    f"/api/v1/documents/{document.id}/pages/{page.page_number}/preview"
                    if page.preview_storage_key
                    else None
                ),
                width=page.width,
                height=page.height,
            )
            for page in pages
        ],
        extractions=[
            DocumentExtractionRead(
                id=extraction.id,
                extraction_type=extraction.extraction_type,
                status=extraction.status,
                summary=extraction.summary,
                confidence=extraction.confidence,
                fields=_extraction_fields(extraction),
                created_at=extraction.created_at,
                updated_at=extraction.updated_at,
            )
            for extraction in extractions
            if extraction.extraction_type != "transaction_draft"
        ],
    )
