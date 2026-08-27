"""Rate limiting on /chat."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter
from app.ratelimit import RateLimiter


@pytest.fixture(autouse=True)
def clear_limiter():
    limiter._hits.clear()
    yield
    limiter._hits.clear()


client = TestClient(app)


def post(ip: str = "1.2.3.4"):
    return client.post("/chat", json={"message": "hi"}, headers={"X-Forwarded-For": ip})


def test_requests_under_the_limit_pass():
    for _ in range(limiter.per_minute):
        assert post().status_code == 200


def test_the_next_request_is_rejected():
    for _ in range(limiter.per_minute):
        post()
    r = post()
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "60"
    assert r.json()["type"] == "error"


def test_clients_are_limited_independently():
    for _ in range(limiter.per_minute):
        post("1.1.1.1")
    assert post("1.1.1.1").status_code == 429
    assert post("2.2.2.2").status_code == 200


def test_health_is_not_rate_limited():
    for _ in range(limiter.per_minute + 5):
        assert client.get("/health").status_code == 200


def test_forwarded_for_takes_the_original_client():
    # A proxy appends its own hops. Limiting on anything but the first entry
    # would bucket every visitor behind one proxy together.
    for _ in range(limiter.per_minute):
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
