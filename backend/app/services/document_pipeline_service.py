import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.extraction import UploadedDocument, extract_from_documents
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.family_scope import (
    RequestContext,
    bind_request_context,
    family_scoped_get,
)
from app.models.document import (
    BackgroundJob,
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentPage,
    DocumentVersion,
)
from app.models.enums import LLMRole
from app.providers.llm import get_active_client
from app.providers.ocr import get_ocr_provider
from app.services.document_ingestion import (
    enrich_vision_extraction,
    local_hash_embedding,
    local_structured_extraction,
    render_document_page,
    split_text,
)
from app.services.document_security_service import inspect_document_content
from app.services.job_event_service import acquire_job_lease, publish_job_update
from app.storage import get_object_storage

settings = get_settings()
logger = logging.getLogger(__name__)


async def _set_progress(
    db: AsyncSession,
    job: BackgroundJob,
    *,
    stage: str,
    progress: int,
    message: str,
) -> None:
    job.stage = stage
    job.progress = progress
    job.message = message
    job.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await publish_job_update(job.family_id, job.id)


async def _vision_extract(
    db: AsyncSession,
    document: Document,
    source: bytes,
    pages: list[tuple[int, str]],
) -> dict | None:
    try:
        client = await get_active_client(db, LLMRole.VISION)
        result = await extract_from_documents(
            [
                UploadedDocument(
                    filename=document.filename,
                    content_type=document.content_type,
                    content=source,
                )
            ],
            client,
        )
    except Exception as exc:
        logger.info("document vision extraction unavailable: %s", type(exc).__name__)
        return None
    enriched = enrich_vision_extraction(result.model_dump(), pages)
    if len(pages) > settings.document_vision_max_pages:
        enriched.setdefault("warnings", []).append(
            "Vision extraction was limited to the first "
            f"{settings.document_vision_max_pages} pages; OCR/RAG indexed every page."
        )
    return enriched


async def _prepare_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    family_id: uuid.UUID,
) -> tuple[BackgroundJob, Document, DocumentVersion] | None:
    bind_request_context(
        db,
        RequestContext(
            user_id=uuid.UUID(int=0),
            family_id=family_id,
            role="worker",
            token_jti=uuid.UUID(int=0),
        ),
    )
    job = (
        await db.execute(
            select(BackgroundJob)
            .where(BackgroundJob.id == job_id, BackgroundJob.family_id == family_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise ValueError("background_job_not_found")
    if job.status == "succeeded":
        return None
    if job.status == "cancelled":
        return None
    bind_request_context(
        db,
        RequestContext(
            user_id=job.created_by_user_id or uuid.UUID(int=0),
            family_id=family_id,
            role="worker",
            token_jti=uuid.UUID(int=0),
        ),
    )
    document = await family_scoped_get(db, Document, job.resource_id)
    if document is None:
        raise ValueError("document_not_found")
    version_id = uuid.UUID(str(job.input_json["document_version_id"]))
    version = await family_scoped_get(db, DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        raise ValueError("document_version_not_found")
    job.status = "running"
    job.stage = "validating"
    job.progress = 2
    job.message = "Validating private source object"
    job.started_at = job.started_at or datetime.now(timezone.utc)
    job.heartbeat_at = datetime.now(timezone.utc)
    job.attempt_count += 1
    document.status = "processing"
    document.error = None
    await db.commit()
    await publish_job_update(job.family_id, job.id)
    return job, document, version


async def _run_document_pipeline(
    db: AsyncSession,
    job: BackgroundJob,
    document: Document,
    version: DocumentVersion,
) -> None:
    storage = get_object_storage(version.storage_backend)
    source = await storage.get_bytes(version.storage_key)
    inspection = await inspect_document_content(
        source,
        version.content_type,
        expected_size=version.size_bytes,
        expected_sha256=version.actual_sha256 or version.expected_sha256,
    )
    await _set_progress(
        db,
        job,
        stage="paginating",
        progress=10,
        message="Rendering protected page previews",
    )

    # Reprocessing supersedes old derived data. Confirmed/cancelled transaction
    # drafts are retained as audit evidence; pending drafts become unusable.
    pending_drafts = list(
        (
            await db.execute(
                select(DocumentExtraction).where(
                    DocumentExtraction.document_id == document.id,
                    DocumentExtraction.extraction_type == "transaction_draft",
                    DocumentExtraction.status == "pending_review",
                )
            )
        ).scalars()
    )
    for draft in pending_drafts:
        draft.status = "failed"
        draft.error = "document_reprocessed"
        draft.resolved_at = datetime.now(timezone.utc)
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    await db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    await db.execute(
        delete(DocumentExtraction).where(
            DocumentExtraction.document_id == document.id,
            DocumentExtraction.extraction_type != "transaction_draft",
        )
    )
    await db.commit()

    page_rows: list[DocumentPage] = []
    ocr_warnings: list[str] = []
    for index in range(1, inspection.page_count + 1):
        rendered = await asyncio.to_thread(
            render_document_page,
            source,
            version.content_type,
            index,
        )
        progress = 15 + int(index / max(1, inspection.page_count) * 42)
        await _set_progress(
            db,
            job,
            stage="ocr",
            progress=progress,
            message=f"OCR page {index} of {inspection.page_count}",
        )
        preview_key = (
            f"families/{document.family_id}/documents/{document.id}/"
            f"versions/{version.version_number}/pages/{rendered.page_number}.png"
        )
        await storage.put_bytes(preview_key, rendered.image, rendered.content_type)
        text = rendered.embedded_text
        confidence: float | None = 0.99 if len(text.strip()) >= 20 else None
        provider = "pdf_text" if confidence is not None else None
        boxes: list = []
        error: str | None = None
        if confidence is None:
            try:
                ocr = await get_ocr_provider().recognize(
                    rendered.image,
                    rendered.content_type,
                )
                text = ocr.text
                confidence = ocr.confidence
                provider = ocr.provider
                boxes = ocr.bounding_boxes
            except Exception as exc:
                provider = "unavailable"
                confidence = 0.0
                error = str(exc)[:300]
                ocr_warnings.append(f"Page {index}: OCR unavailable")
        row = DocumentPage(
            family_id=document.family_id,
            document_id=document.id,
            document_version_id=version.id,
            page_number=rendered.page_number,
            status="failed" if error and not text.strip() else "ready",
            width=rendered.width,
            height=rendered.height,
            extracted_text=text,
            ocr_provider=provider,
            ocr_confidence=confidence,
            bounding_boxes_json=boxes,
            preview_storage_key=preview_key,
            preview_content_type=rendered.content_type,
            error=error,
        )
        db.add(row)
        await db.flush()
        page_rows.append(row)
    document.page_count = len(page_rows)
    await db.commit()

    await _set_progress(
        db,
        job,
        stage="extracting",
        progress=63,
        message="Extracting structured financial fields",
    )
    page_texts = [(page.page_number, page.extracted_text or "") for page in page_rows]
    local = local_structured_extraction(
        page_texts,
        document_type=document.document_type,
    )
    vision = await _vision_extract(db, document, source, page_texts)
    structured = vision if vision and (vision.get("fields") or vision.get("items")) else local
    provider = "vision" if structured is vision else "local"
    structured["warnings"] = list(structured.get("warnings") or []) + ocr_warnings
    citations = [
        {
            "page_number": field.get("page_number"),
            "citation": field.get("citation"),
        }
        for field in structured.get("fields", [])
        if field.get("page_number")
    ]
    extraction = DocumentExtraction(
        family_id=document.family_id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_type="financial_document",
        schema_version=1,
        status="ready",
        summary=structured.get("summary"),
        confidence=structured.get("confidence"),
        provider=provider,
        data_json=structured,
        citations_json=citations,
    )
    db.add(extraction)
    await db.commit()

    await _set_progress(
        db,
        job,
        stage="chunking",
        progress=74,
        message="Chunking document with LlamaIndex-compatible ingestion",
    )
    chunk_index = 0
    chunks: list[DocumentChunk] = []
    for page in page_rows:
        page_chunks = split_text(page.extracted_text or "")
        for content in page_chunks:
            chunks.append(
                DocumentChunk(
                    family_id=document.family_id,
                    document_id=document.id,
                    document_version_id=version.id,
                    document_page_id=page.id,
                    page_number=page.page_number,
                    chunk_index=chunk_index,
                    content=content,
                    token_count=max(1, len(content.split())),
                    metadata_json={
                        "document_type": document.document_type,
                        "document_date": (
                            document.document_date.isoformat() if document.document_date else None
                        ),
                        "institution_id": (
                            str(document.institution_id) if document.institution_id else None
                        ),
                        "account_id": str(document.account_id) if document.account_id else None,
                    },
                    bounding_boxes_json=page.bounding_boxes_json or [],
                    embedding=local_hash_embedding(content),
                )
            )
            chunk_index += 1
    if not chunks and structured.get("items"):
        for item in structured["items"]:
            content = " | ".join(
                f"{key}: {value}"
                for key, value in item.items()
                if value not in (None, "", [])
                and key not in {"confidence", "page_number", "citation"}
            )
            page_number = int(item.get("page_number") or 1)
            page = next((candidate for candidate in page_rows if candidate.page_number == page_number), page_rows[0])
            chunks.append(
                DocumentChunk(
                    family_id=document.family_id,
                    document_id=document.id,
                    document_version_id=version.id,
                    document_page_id=page.id,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    content=content,
                    token_count=max(1, len(content.split())),
                    metadata_json={"derived_from": "structured_extraction"},
                    bounding_boxes_json=[],
                    embedding=local_hash_embedding(content),
                )
            )
            chunk_index += 1
    db.add_all(chunks)
    await _set_progress(
        db,
        job,
        stage="indexing",
        progress=92,
        message="Writing pgvector and full-text indexes",
    )

    now = datetime.now(timezone.utc)
    document.status = "ready"
    document.error = None
    version.status = "ready"
    job.status = "succeeded"
    job.stage = "completed"
    job.progress = 100
    job.message = "Document processing complete"
    job.result_json = {
        "document_id": str(document.id),
        "document_version_id": str(version.id),
        "page_count": len(page_rows),
        "chunk_count": len(chunks),
        "extraction_id": str(extraction.id),
        "extraction_provider": provider,
        "security_warnings": list(inspection.warnings),
        "warnings": structured.get("warnings") or [],
    }
    job.finished_at = now
    job.heartbeat_at = now
    await db.commit()
    await publish_job_update(job.family_id, job.id)


async def _mark_failed(
    job_id: uuid.UUID,
    family_id: uuid.UUID,
    error: Exception,
) -> None:
    async with AsyncSessionLocal() as db:
        bind_request_context(
            db,
            RequestContext(
                user_id=uuid.UUID(int=0),
                family_id=family_id,
                role="worker",
                token_jti=uuid.UUID(int=0),
            ),
        )
        row = (
            await db.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.family_id == family_id)
            )
        ).scalar_one_or_none()
        if row is None or row.status in {"succeeded", "cancelled"}:
            return
        bind_request_context(
            db,
            RequestContext(
                user_id=row.created_by_user_id or uuid.UUID(int=0),
                family_id=family_id,
                role="worker",
                token_jti=uuid.UUID(int=0),
            ),
        )
        safe_error = f"document_processing_failed:{type(error).__name__}"[:300]
        row.status = "failed"
        row.stage = "failed"
        row.error = safe_error
        row.message = "Document processing failed"
        row.finished_at = datetime.now(timezone.utc)
        document = (
            await family_scoped_get(db, Document, row.resource_id)
            if row.resource_id is not None
            else None
        )
        if document is not None:
            document.status = "failed"
            document.error = safe_error
        await db.commit()
        await publish_job_update(row.family_id, row.id)


async def process_document_job(
    job_id: uuid.UUID | str,
    family_id: uuid.UUID | str,
) -> None:
    """Serializable worker entry used by Celery and local BackgroundTasks."""

    parsed_job_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
    parsed_family_id = (
        family_id if isinstance(family_id, uuid.UUID) else uuid.UUID(str(family_id))
    )
    try:
        async with acquire_job_lease(parsed_job_id) as acquired:
            if not acquired:
                return
            async with AsyncSessionLocal() as db:
                prepared = await _prepare_job(
                    db,
                    parsed_job_id,
                    parsed_family_id,
                )
                if prepared is None:
                    return
                await _run_document_pipeline(db, *prepared)
    except Exception as exc:
        logger.exception("document processing failed job_id=%s", parsed_job_id)
        await _mark_failed(parsed_job_id, parsed_family_id, exc)
        if isinstance(exc, ConnectionError):
            raise


def enqueue_document_job(
    background_tasks: BackgroundTasks,
    job: BackgroundJob,
) -> str:
    """Prefer Celery when configured; explicitly fall back in development."""

    backend = settings.document_job_backend.lower()
    should_try_celery = backend == "celery" or (
        backend == "auto" and bool(settings.celery_broker_url)
    )
    if should_try_celery:
        try:
            from app.worker import celery_app

            if celery_app is None:
                raise RuntimeError("celery_not_installed")
            celery_app.send_task(
                "documents.process",
                args=[str(job.id), str(job.family_id)],
            )
            return "celery"
        except Exception:
            if not settings.document_inline_fallback:
                raise RuntimeError("document_job_enqueue_failed") from None
            logger.warning("Celery enqueue unavailable; using BackgroundTasks", exc_info=True)
    background_tasks.add_task(process_document_job, job.id, job.family_id)
    return "background"
