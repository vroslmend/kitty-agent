"""Per-client rate limiting for the chat endpoint.

In-process and per-instance. That is enough while this runs as a single
container, and it is the wrong tool the moment it runs as several: each would
enforce its own allowance. Move to a shared store before scaling out.
"""

import time
from collections import defaultdict, deque

from fastapi import Request

# Stop the table growing without bound when traffic is spread over many
# addresses. Evicting the coldest is fine: an evicted client starts with a
# fresh allowance, which is the same position a new one is in.
MAX_TRACKED_CLIENTS = 10_000


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        window = self._hits[key]
        cutoff = now - 60.0
        while window and window[0] <= cutoff:
            window.popleft()
        return window

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self._prune(key, now)

        if len(window) >= self.per_minute:
            return False

        window.append(now)

        if len(self._hits) > MAX_TRACKED_CLIENTS:
            self._evict_cold(now)

        return True

    def _evict_cold(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - 60.0]:
            del self._hits[key]


def client_key(request: Request) -> str:
    """Identify the caller.

    Render and every other proxy terminate the connection themselves, so
    request.client.host is the proxy and would put every visitor in one bucket.
    The original address is the first entry in X-Forwarded-For.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
