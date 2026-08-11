import asyncio
from collections.abc import Awaitable
from typing import Any

from app.core.config import get_settings
from app.services.agent_job_service import process_agent_job
from app.services.document_pipeline_service import process_document_job
from app.services.price_job_service import process_price_refresh_job

settings = get_settings()
_worker_event_loop: asyncio.AbstractEventLoop | None = None


def _run_async(awaitable: Awaitable[Any]) -> Any:
    """Run all async jobs on one event loop per Celery worker process.

    The global SQLAlchemy async engine pools asyncpg connections that belong to
    their creating loop. ``asyncio.run`` creates and destroys a loop for every
    task, so a later task can receive a pooled connection attached to a closed
    loop. Keeping one loop per worker process preserves loop ownership.
    """

    global _worker_event_loop
    if _worker_event_loop is None or _worker_event_loop.is_closed():
        _worker_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_event_loop)
    return _worker_event_loop.run_until_complete(awaitable)


def _close_worker_event_loop(**_: Any) -> None:
    global _worker_event_loop
    loop, _worker_event_loop = _worker_event_loop, None
    if loop is None or loop.is_closed():
        return

    from app.core.db import engine

    loop.run_until_complete(engine.dispose())
    loop.close()


try:
    from celery import Celery
except ImportError:  # pragma: no cover - local fallback deliberately supports this
    celery_app = None
else:
    from celery.signals import worker_process_shutdown, worker_shutdown

    celery_app = Celery(
        "wealthportfolio",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_cancel_long_running_tasks_on_connection_loss=True,
    )
    worker_process_shutdown.connect(_close_worker_event_loop, weak=False)
    worker_shutdown.connect(_close_worker_event_loop, weak=False)

    @celery_app.task(
        name="documents.process",
        autoretry_for=(ConnectionError,),
        retry_backoff=True,
        retry_kwargs={"max_retries": 3},
    )
    def process_document_task(job_id: str, family_id: str) -> None:
        _run_async(process_document_job(job_id, family_id))

    @celery_app.task(
        name="agent.run",
        autoretry_for=(ConnectionError,),
        retry_backoff=True,
        retry_kwargs={"max_retries": 3},
    )
    def process_agent_task(
        job_id: str,
        family_id: str,
        user_id: str,
    ) -> None:
        _run_async(process_agent_job(job_id, family_id, user_id))

    @celery_app.task(
        name="prices.refresh",
        autoretry_for=(ConnectionError,),
        retry_backoff=True,
        retry_kwargs={"max_retries": 3},
    )
    def process_price_refresh_task(
        job_id: str,
        family_id: str,
        user_id: str,
    ) -> None:
        _run_async(process_price_refresh_job(job_id, family_id, user_id))
