import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    """Simple in-process rate limiter keyed by an arbitrary string (e.g. client IP).

    Good enough for a single-instance family-scale deployment. If the backend is ever
    scaled to multiple processes/workers, replace with a Redis-backed limiter.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()

    def is_allowed(self, key: str) -> bool:
        self._prune(key)
        return len(self._attempts[key]) < self.max_attempts

    def record_attempt(self, key: str) -> None:
        self._attempts[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


login_rate_limiter = InMemoryRateLimiter(max_attempts=5, window_seconds=300)
