"""Smoke tests: the service boots, CORS is wired, SSE frames parse."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import NAPPING, app

client = TestClient(app)


def test_health_reports_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "kitty-agent"


def test_health_reports_agent_not_ready_without_a_key():
    # No LLM_API_KEY in the test env, so the agent must advertise itself as down
    # rather than claiming readiness it does not have.
    assert client.get("/health").json()["agent_ready"] is False


def parse_sse(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.strip().split("\n\n")
        if line.startswith("data: ")
    ]


def test_chat_streams_the_napping_fallback():
    r = client.post("/chat", json={"message": "who are you"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(r.text)
    assert [e["type"] for e in events] == ["step", "token", "done"]
    assert events[1]["text"] == NAPPING


def test_chat_keeps_a_supplied_thread_id():
    r = client.post("/chat", json={"message": "hi", "thread_id": "abc-123"})
    assert parse_sse(r.text)[-1]["thread_id"] == "abc-123"


def test_chat_mints_a_thread_id_when_absent():
    r = client.post("/chat", json={"message": "hi"})
    assert parse_sse(r.text)[-1]["thread_id"]


@pytest.mark.parametrize("payload", [{"message": ""}, {}, {"message": "x" * 2001}])
def test_chat_rejects_bad_input(payload):
    assert client.post("/chat", json=payload).status_code == 422
