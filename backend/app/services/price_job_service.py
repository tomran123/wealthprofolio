import logging
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context, family_scoped_get
from app.models.document import BackgroundJob
from app.services import price_refresh_service
from app.services.job_event_service import acquire_job_lease, publish_job_update

settings = get_settings()
logger = logging.getLogger(__name__)


def _worker_context(family_id: uuid.UUID, user_id: uuid.UUID) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        family_id=family_id,
        role="worker",
        token_jti=uuid.UUID(int=0),
    )


async def process_price_refresh_job(
    job_id: uuid.UUID | str,
    family_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
) -> None:
    parsed_job_id = uuid.UUID(str(job_id))
    parsed_family_id = uuid.UUID(str(family_id))
    parsed_user_id = uuid.UUID(str(user_id))
    started = False
    try:
        async with acquire_job_lease(parsed_job_id) as acquired:
            if not acquired:
                return
            async with AsyncSessionLocal() as db:
                bind_request_context(
                    db,
                    _worker_context(parsed_family_id, parsed_user_id),
                )
                job = (
                    await db.execute(
                        select(BackgroundJob)
                        .where(BackgroundJob.id == parsed_job_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if job is None or job.status in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    return
                if job.status == "running":
                    finished_at = datetime.now(timezone.utc)
                    job.status = "failed"
                    job.stage = "failed"
                    job.progress = min(job.progress, 99)
                    job.message = (
                        "Price refresh worker was interrupted; start a new refresh"
                    )
                    job.error = "price_refresh_interrupted"
                    job.finished_at = finished_at
                    job.heartbeat_at = finished_at
                    await db.commit()
                    await publish_job_update(parsed_family_id, parsed_job_id)
                    return
                now = datetime.now(timezone.utc)
                job.status = "running"
                job.stage = "market_data"
                job.progress = 10
                job.message = "Refreshing market prices and FX rates"
                job.error = None
                job.attempt_count += 1
                job.started_at = job.started_at or now
                job.heartbeat_at = now
                await db.commit()
                started = True
                await publish_job_update(parsed_family_id, parsed_job_id)

                result = await price_refresh_service.refresh_all_prices(db)
                job = await family_scoped_get(db, BackgroundJob, parsed_job_id)
                if job is None:
                    return
                finished_at = datetime.now(timezone.utc)
                job.status = "succeeded"
                job.stage = "complete"
                job.progress = 100
                job.message = "Price refresh complete"
                job.result_json = result
                job.resource_type = "valuation_snapshot"
                job.resource_id = uuid.UUID(str(result["snapshot_id"]))
                job.finished_at = finished_at
                job.heartbeat_at = finished_at
                await db.commit()
                await publish_job_update(parsed_family_id, parsed_job_id)
    except Exception as exc:
        logger.error(
            "price refresh job failed job_id=%s error_type=%s",
            parsed_job_id,
            type(exc).__name__,
        )
        # Preserve ``queued`` for a Celery retry when infrastructure failed
        # before the job durably entered ``running``.
        if not started and isinstance(exc, ConnectionError):
            raise
        async with AsyncSessionLocal() as db:
            bind_request_context(
                db,
                _worker_context(parsed_family_id, parsed_user_id),
            )
            job = await family_scoped_get(db, BackgroundJob, parsed_job_id)
            if job is None or job.status in {"succeeded", "cancelled"}:
                return
            job.status = "failed"
            job.stage = "failed"
            job.progress = min(job.progress, 99)
            job.message = "Price refresh failed"
            job.error = f"price_refresh_failed:{type(exc).__name__}"[:300]
            job.finished_at = datetime.now(timezone.utc)
            job.heartbeat_at = job.finished_at
            await db.commit()
            await publish_job_update(parsed_family_id, parsed_job_id)


def enqueue_price_refresh_job(
    background_tasks: BackgroundTasks,
    job: BackgroundJob,
) -> str:
    backend = settings.price_job_backend.lower()
    should_try_celery = backend == "celery" or (
        backend == "auto" and bool(settings.celery_broker_url)
    )
    if should_try_celery:
        try:
            from app.worker import celery_app

            if celery_app is None:
                raise RuntimeError("celery_not_installed")
            celery_app.send_task(
                "prices.refresh",
                args=[
                    str(job.id),
                    str(job.family_id),
                    str(job.created_by_user_id),
                ],
            )
            return "celery"
        except Exception:
            if not settings.price_inline_fallback:
                raise RuntimeError("price_job_enqueue_failed") from None
            logger.warning(
                "Celery enqueue unavailable; using BackgroundTasks",
                exc_info=True,
            )
    background_tasks.add_task(
        process_price_refresh_job,
        job.id,
        job.family_id,
        job.created_by_user_id,
    )
    return "background"
