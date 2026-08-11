import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

settings = get_settings()
logger = logging.getLogger(__name__)


def job_channel(family_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"wealthportfolio:jobs:{family_id}:{job_id}"


@asynccontextmanager
async def acquire_job_lease(job_id: uuid.UUID) -> AsyncIterator[bool]:
    """Hold a PostgreSQL session lock for the complete worker attempt.

    The lock is released by PostgreSQL when a killed worker loses its database
    connection, so an immediately redelivered RabbitMQ message can inspect the
    durable ``running`` row. A concurrent duplicate delivery blocks until the
    current owner finishes, then observes the terminal row without executing
    side effects. Blocking avoids a try-lock release race that could otherwise
    acknowledge the only redelivery just before PostgreSQL releases the lock.
    """

    lock_name = f"wealthportfolio:background-job:{job_id}"
    async with engine.connect() as connection:
        await connection.execute(
            text(
                "SELECT pg_advisory_lock("
                "hashtextextended(:lock_name, 0))"
            ),
            {"lock_name": lock_name},
        )
        try:
            yield True
        finally:
            with suppress(Exception):
                await connection.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended(:lock_name, 0))"
                    ),
                    {"lock_name": lock_name},
                )


async def publish_job_update(family_id: uuid.UUID, job_id: uuid.UUID) -> bool:
    """Best-effort Redis wakeup; PostgreSQL remains the durable job truth."""

    if not settings.redis_url:
        return False
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.publish(job_channel(family_id, job_id), "updated")
        finally:
            await client.aclose()
        return True
    except Exception as exc:
        logger.info("job pubsub unavailable; websocket will poll: %s", type(exc).__name__)
        return False
