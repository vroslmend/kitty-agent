"""Rate limiting on /chat."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter
from app.ratelimit import (
    SWEEP,
    SWEEP_EVERY,
    TAKE,
    ChatRateLimiter,
    RateLimiter,
    SharedRateLimiter,
)


@pytest.fixture(autouse=True)
def clear_limiter():
    limiter.local._hits.clear()
    yield
    limiter.local._hits.clear()


client = TestClient(app)


def post(ip: str = "1.2.3.4"):
    return client.post("/chat", json={"message": "hi"}, headers={"X-Forwarded-For": ip})


def test_requests_under_the_limit_pass():
    for _ in range(limiter.local.per_minute):
        assert post().status_code == 200


def test_the_next_request_is_rejected():
    for _ in range(limiter.local.per_minute):
        post()
    r = post()
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "60"
    assert r.json()["type"] == "error"


def test_clients_are_limited_independently():
    for _ in range(limiter.local.per_minute):
        post("1.1.1.1")
    assert post("1.1.1.1").status_code == 429
    assert post("2.2.2.2").status_code == 200


def test_health_is_not_rate_limited():
    for _ in range(limiter.local.per_minute + 5):
        assert client.get("/health").status_code == 200


def test_forwarded_for_takes_the_original_client():
    # A proxy appends its own hops. Limiting on anything but the first entry
    # would bucket every visitor behind one proxy together.
    for _ in range(limiter.local.per_minute):
        client.post(
            "/chat",
            json={"message": "hi"},
            headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1, 10.0.0.2"},
        )
    blocked = client.post("/chat", json={"message": "hi"}, headers={"X-Forwarded-For": "9.9.9.9"})
    assert blocked.status_code == 429


def test_window_is_a_rolling_minute():
    rl = RateLimiter(per_minute=2)
    assert rl.allow("k") and rl.allow("k")
    assert not rl.allow("k")

    # Age the recorded hits past the window rather than sleeping 60s.
    rl._hits["k"] = type(rl._hits["k"])(t - 61 for t in rl._hits["k"])
    assert rl.allow("k")


def test_cold_clients_are_evicted():
    rl = RateLimiter(per_minute=1)
    now = time.monotonic()
    for i in range(3):
        rl._hits[f"old-{i}"].append(now - 120)
    rl._evict_cold(now)
    assert not any(k.startswith("old-") for k in rl._hits)


class FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, row, fail=False):
        self._row = row
        self._fail = fail
        self.statements = []

    async def execute(self, statement, params=None):
        if self._fail:
            raise RuntimeError("connection lost")
        self.statements.append(statement)
        return FakeCursor(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return self._conn


def pool_of(conn):
    async def provider():
        return FakePool(conn)

    return provider


async def test_shared_returns_the_database_verdict():
    for verdict in (True, False):
        shared = SharedRateLimiter(10, pool_of(FakeConnection({"allowed": verdict})))
        assert await shared.allow("k") is verdict


async def test_shared_falls_back_to_allowing_when_the_database_is_down():
    # The local window has already counted the request by this point, so the
    # endpoint is still bounded. Refusing here would turn a database outage
    # into a 429 for every visitor.
    shared = SharedRateLimiter(10, pool_of(FakeConnection(None, fail=True)))
    assert await shared.allow("k") is True


async def test_the_sweep_runs_once_and_then_holds_off():
    # A cold instance must sweep on its first call. Timing this against zero
    # instead of against "not yet" reads as correct and skips that sweep on any
    # host whose monotonic clock started less than the interval ago, which is
    # every fresh CI runner.
    conn = FakeConnection({"allowed": True})
    shared = SharedRateLimiter(10, pool_of(conn))
    for _ in range(3):
        await shared.allow("k")
    assert sum(s == SWEEP for s in conn.statements) == 1


async def test_the_sweep_comes_back_round_after_the_interval():
    conn = FakeConnection({"allowed": True})
    shared = SharedRateLimiter(10, pool_of(conn))
    await shared.allow("k")
    shared._swept_at -= SWEEP_EVERY + 1
    await shared.allow("k")
    assert sum(s == SWEEP for s in conn.statements) == 2


async def test_a_local_refusal_never_reaches_the_database():
    conn = FakeConnection({"allowed": True})
    chat = ChatRateLimiter(1, pool_of(conn))
    assert await chat.allow("k") is True
    assert await chat.allow("k") is False
    assert sum(s == TAKE for s in conn.statements) == 1


async def test_without_a_pool_only_the_local_window_applies():
    chat = ChatRateLimiter(2)
    assert chat.shared is None
    assert await chat.allow("k") and await chat.allow("k")
    assert not await chat.allow("k")
