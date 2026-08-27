"""Per-client rate limiting for the chat endpoint.

Two limiters, and a request has to pass both.

The local one counts in process, so on serverless it sees one instance's share
of a client's traffic and nothing else. The shared one counts in Postgres,
which is the only place several instances can agree. Local runs first because
it costs nothing, and it is what still bounds the endpoint if the database is
unreachable.
"""

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request

# Stop the table growing without bound when traffic is spread over many
# addresses. Evicting the coldest is fine: an evicted client starts with a
# fresh allowance, which is the same position a new one is in.
MAX_TRACKED_CLIENTS = 10_000

log = logging.getLogger(__name__)


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


SCHEMA = (
    """
    create table if not exists rate_limit_hits (
        id bigserial primary key,
        client_key text not null,
        at timestamptz not null default now()
    )
    """,
    "create index if not exists rate_limit_hits_window on rate_limit_hits (client_key, at)",
)

# `recent` selects from `locked` so that it cannot produce a count until the
# lock has been taken. Nothing else orders the parts of a CTE, and without the
# ordering two instances read the same under-limit count and both insert.
#
# The lock is transaction scoped and the pool runs in autocommit, so it is held
# for exactly this statement. Do not turn autocommit off here: the lock would
# then survive until whoever owns the transaction commits.
TAKE = """
with locked as (
    select pg_advisory_xact_lock(hashtextextended(%(key)s, 0))
),
recent as (
    select count(*) as n
    from rate_limit_hits, locked
    where client_key = %(key)s and at > now() - interval '60 seconds'
),
taken as (
    insert into rate_limit_hits (client_key)
    select %(key)s from recent where n < %(limit)s
    returning 1
)
select exists (select 1 from taken) as allowed
"""

SWEEP = "delete from rate_limit_hits where at <= now() - interval '60 seconds'"

# Only expired rows, and the window filter in TAKE means no answer depends on
# this having run. It is housekeeping, so it is cheap to do rarely.
SWEEP_EVERY = 60.0

PoolProvider = Callable[[], Awaitable]


class SharedRateLimiter:
    def __init__(self, per_minute: int, pool_provider: PoolProvider) -> None:
        self.per_minute = per_minute
        self._pool_provider = pool_provider
        self._swept_at: float | None = None

    async def allow(self, key: str) -> bool:
        try:
            pool = await self._pool_provider()
            async with pool.connection() as conn:
                cur = await conn.execute(TAKE, {"key": key, "limit": self.per_minute})
                row = await cur.fetchone()
                allowed = bool(row and row["allowed"])
                await self._sweep(conn)
                return allowed
        except Exception:
            # Allowing here is not a bypass: the local limiter has already
            # counted this request, so the endpoint stays bounded, just per
            # instance. Failing closed would take the agent down with the
            # database and hand a visitor a 429 for a fault that is ours.
            log.exception("shared rate limit unavailable, falling back to the local window")
            return True

    async def _sweep(self, conn) -> None:
        now = time.monotonic()
        # None, not 0.0. monotonic() counts from an arbitrary origin, usually
        # boot, so on a host that started a moment ago 0.0 is seconds back and
        # the first sweep of a cold instance never runs.
        if self._swept_at is not None and now - self._swept_at < SWEEP_EVERY:
            return
        self._swept_at = now
        await conn.execute(SWEEP)


class ChatRateLimiter:
    """The limiter `/chat` actually calls. Local first, then shared."""

    def __init__(self, per_minute: int, pool_provider: PoolProvider | None = None) -> None:
        self.local = RateLimiter(per_minute)
        self.shared = SharedRateLimiter(per_minute, pool_provider) if pool_provider else None

    async def allow(self, key: str) -> bool:
        if not self.local.allow(key):
            return False
        if self.shared is None:
            return True
        return await self.shared.allow(key)


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
