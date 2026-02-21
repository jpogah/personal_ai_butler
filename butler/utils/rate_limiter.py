"""Sliding-window rate limiter per sender."""
import asyncio
import time
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window token bucket: limits messages per minute per sender."""

    def __init__(self, messages_per_minute: int = 10, burst: int = 3):
        self._limit = messages_per_minute
        self._burst = burst
        self._window = 60.0  # seconds
        # sender_id → deque of timestamps
        self._buckets: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, sender_id: str) -> bool:
        """Return True if sender is within rate limit, False if throttled."""
        async with self._lock:
            now = time.monotonic()
            bucket = self._buckets[sender_id]
            # Evict timestamps older than window
            cutoff = now - self._window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._limit:
                logger.warning("Rate limit exceeded for sender %s", sender_id)
                return False

            bucket.append(now)
            return True

    async def reset(self, sender_id: str) -> None:
        async with self._lock:
            self._buckets.pop(sender_id, None)
