import logging
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.agent.agent import run_agent_turn
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context, family_scoped_get
from app.models.document import BackgroundJob
from app.schemas.agent import AgentChatRequest
from app.services.job_event_service import acquire_job_lease, publish_job_update

settings = get_settings()
logger = logging.getLogger(__name__)


def _worker_context(
    family_id: uuid.UUID,
    user_id: uuid.UUID,
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        family_id=family_id,
        role="worker",
        token_jti=uuid.UUID(int=0),
    )


async def _mark_failed(
    job_id: uuid.UUID,
    family_id: uuid.UUID,
    user_id: uuid.UUID,
    error: Exception,
) -> None:
    async with AsyncSessionLocal() as db:
        bind_request_context(db, _worker_context(family_id, user_id))
        job = await family_scoped_get(db, BackgroundJob, job_id)
        if job is None or job.status in {"succeeded", "cancelled"}:
            return
        logger.error(
            "agent job failed job_id=%s error_type=%s",
            job_id,
            type(error).__name__,
        )
        job.status = "failed"
        job.stage = "failed"
        job.progress = min(job.progress, 99)
        job.message = "Agent request failed"
        # Provider responses can include sensitive request fragments. Persist a
        # stable error code, while full diagnostics stay in protected logs.
        job.error = (
            str(error)
            if isinstance(error, (ValueError, RuntimeError))
            and str(error).replace("_", "").isalnum()
            else f"agent_job_failed:{type(error).__name__}"
        )[:300]
        job.finished_at = datetime.now(timezone.utc)
        job.heartbeat_at = job.finished_at
        await db.commit()
        await publish_job_update(family_id, job_id)


async def process_agent_job(
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
                if job is None:
                    return
                if job.status in {"succeeded", "failed", "cancelled"}:
                    return
                if job.status == "running":
                    finished_at = datetime.now(timezone.utc)
                    job.status = "failed"
                    job.stage = "failed"
                    job.progress = min(job.progress, 99)
                    job.message = "Agent worker was interrupted; submit the request again"
                    job.error = "agent_job_interrupted"
                    job.finished_at = finished_at
                    job.heartbeat_at = finished_at
                    await db.commit()
                    await publish_job_update(parsed_family_id, parsed_job_id)
                    return
                payload = AgentChatRequest.model_validate(job.input_json)
                now = datetime.now(timezone.utc)
                job.status = "running"
                job.stage = "agent"
                job.progress = 10
                job.message = "Agent is processing the request"
                job.error = None
                job.attempt_count += 1
                job.started_at = job.started_at or now
                job.heartbeat_at = now
                await db.commit()
                started = True
                await publish_job_update(parsed_family_id, parsed_job_id)

                result = await run_agent_turn(
                    db,
                    payload.messages,
                    payload.session_id,
                )
                job = await family_scoped_get(db, BackgroundJob, parsed_job_id)
                if job is None:
                    return
                finished_at = datetime.now(timezone.utc)
                job.status = "succeeded"
                job.stage = "complete"
                job.progress = 100
                job.message = "Agent request complete"
                job.result_json = result.model_dump(mode="json")
                job.resource_type = "agent_session"
                job.resource_id = result.session_id
                job.finished_at = finished_at
                job.heartbeat_at = finished_at
                await db.commit()
                await publish_job_update(parsed_family_id, parsed_job_id)
    except Exception as exc:
        # Let Celery retry connection failures that happened before the job
        # durably entered ``running``. Marking the row failed first would make
        # the retry return immediately on the terminal status.
        if not started and isinstance(exc, ConnectionError):
            raise
        await _mark_failed(
            parsed_job_id,
            parsed_family_id,
            parsed_user_id,
            exc,
        )


def enqueue_agent_job(
    background_tasks: BackgroundTasks,
    job: BackgroundJob,
) -> str:
    backend = settings.agent_job_backend.lower()
    should_try_celery = backend == "celery" or (
        backend == "auto" and bool(settings.celery_broker_url)
    )
    if should_try_celery:
        try:
            from app.worker import celery_app

            if celery_app is None:
                raise RuntimeError("celery_not_installed")
            celery_app.send_task(
                "agent.run",
                args=[
                    str(job.id),
                    str(job.family_id),
                    str(job.created_by_user_id),
                ],
            )
            return "celery"
        except Exception:
            if not settings.agent_inline_fallback:
                raise RuntimeError("agent_job_enqueue_failed") from None
            logger.warning(
                "Celery enqueue unavailable; using BackgroundTasks",
                exc_info=True,
            )
    background_tasks.add_task(
        process_agent_job,
        job.id,
        job.family_id,
        job.created_by_user_id,
    )
    return "background"
