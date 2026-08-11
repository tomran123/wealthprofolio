"""Small best-effort Redis primitives for distributed ephemeral state."""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def redis_get(key: str) -> tuple[bool, str | None]:
    """Return ``(available, value)`` without turning Redis into a hard dependency."""

    if not settings.redis_url:
        return False, None
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            return True, await client.get(key)
        finally:
            await client.aclose()
    except Exception as exc:
        logger.warning("redis_get_failed error=%s", type(exc).__name__)
        return False, None


async def redis_set(key: str, value: str, *, ttl_seconds: int) -> bool:
    if not settings.redis_url:
        return False
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            await client.set(key, value, ex=ttl_seconds)
        finally:
            await client.aclose()
        return True
    except Exception as exc:
        logger.warning("redis_set_failed error=%s", type(exc).__name__)
        return False


async def redis_delete(key: str) -> bool:
    if not settings.redis_url:
        return False
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            await client.delete(key)
        finally:
            await client.aclose()
        return True
    except Exception as exc:
        logger.warning("redis_delete_failed error=%s", type(exc).__name__)
        return False
