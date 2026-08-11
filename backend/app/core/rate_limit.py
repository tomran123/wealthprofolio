"""Distributed login throttling with an in-process availability fallback."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import defaultdict, deque
from time import monotonic

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_CONSUME_SCRIPT = """
local attempts = redis.call('INCR', KEYS[1])
if attempts == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if attempts <= tonumber(ARGV[2]) then
  return 1
end
return 0
"""


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._redis = None
        self._redis_retry_after = 0.0

    @staticmethod
    def _key(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"wealthportfolio:login-attempts:{digest}"

    async def _redis_client(self):
        redis_url = getattr(settings, "redis_url", None)
        if not redis_url or monotonic() < self._redis_retry_after:
            return None
        if self._redis is None:
            client = None
            try:
                from redis.asyncio import Redis

                client = Redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
                await client.ping()
                self._redis = client
            except Exception as exc:  # Redis is optional for local development.
                self._redis = None
                self._redis_retry_after = monotonic() + 30
                if client is not None:
                    await client.aclose()
                logger.warning(
                    "redis_rate_limit_unavailable error=%s",
                    type(exc).__name__,
                )
        return self._redis

    async def _discard_redis_client(self) -> None:
        client, self._redis = self._redis, None
        self._redis_retry_after = monotonic() + 30
        if client is not None:
            await client.aclose()

    async def consume(self, value: str) -> bool:
        key = self._key(value)
        client = await self._redis_client()
        if client is not None:
            try:
                allowed = await client.eval(
                    _CONSUME_SCRIPT,
                    1,
                    key,
                    self.window_seconds,
                    self.max_attempts,
                )
                return bool(allowed)
            except Exception as exc:
                logger.warning(
                    "redis_rate_limit_failed error=%s",
                    type(exc).__name__,
                )
                await self._discard_redis_client()

        # A per-process fallback is acceptable for local development, but in a
        # horizontally scaled production deployment it can be bypassed by
        # spreading attempts across replicas. Fail closed until Redis recovers.
        if settings.environment in {"production", "prod"}:
            return False

        now = monotonic()
        async with self._lock:
            attempts = self._attempts[key]
            cutoff = now - self.window_seconds
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            attempts.append(now)
            return len(attempts) <= self.max_attempts

    async def reset(self, value: str) -> None:
        key = self._key(value)
        client = await self._redis_client()
        if client is not None:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.warning(
                    "redis_rate_limit_reset_failed error=%s",
                    type(exc).__name__,
                )
                await self._discard_redis_client()
        async with self._lock:
            self._attempts.pop(key, None)


login_rate_limiter = LoginRateLimiter()
